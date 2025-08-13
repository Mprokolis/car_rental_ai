import os, base64, datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from rentals.models import Company, OutlookConnection, ImportedMessage, Booking, Car
from rentals.parsers.united_pdf import parse_united_reservation_text
import requests

try:
    import msal
except ImportError:
    msal = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

GRAPH_SCOPES = getattr(settings, "MS_GRAPH_SCOPES", ["offline_access", "Mail.Read"])
MS_CLIENT_ID = getattr(settings, "MS_GRAPH_CLIENT_ID", None)
MS_CLIENT_SECRET = getattr(settings, "MS_GRAPH_CLIENT_SECRET", None)
MS_TENANT = getattr(settings, "MS_GRAPH_TENANT", "common")

OUTLOOK_FILTER_FROM = getattr(settings, "OUTLOOK_FILTER_FROM", "")
OUTLOOK_FOLDER = getattr(settings, "OUTLOOK_FOLDER", "Inbox")
IMPORT_TMP_DIR = getattr(settings, "IMPORT_TMP_DIR", os.path.join(os.getcwd(), "tmp_imports"))
os.makedirs(IMPORT_TMP_DIR, exist_ok=True)


def msal_app():
    if not msal:
        raise RuntimeError("msal δεν είναι εγκατεστημένο. pip install msal")
    if not MS_CLIENT_ID or not MS_CLIENT_SECRET:
        raise RuntimeError("Ρύθμισε MS_GRAPH_CLIENT_ID/SECRET.")
    authority = f"https://login.microsoftonline.com/{MS_TENANT}"
    return msal.ConfidentialClientApplication(
        MS_CLIENT_ID, authority=authority, client_credential=MS_CLIENT_SECRET
    )

def acquire_token_silent(conn: OutlookConnection):
    app = msal_app()
    token = conn.token_json or {}
    accounts = app.get_accounts(username=conn.account_upn) if conn.account_upn else []
    result = None
    if accounts:
        result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
    if not result and token.get("refresh_token"):
        result = app.acquire_token_by_refresh_token(token["refresh_token"], scopes=GRAPH_SCOPES)
    if result and "access_token" in result:
        conn.token_json = result
        conn.save(update_fields=["token_json", "updated_at"])
        return result["access_token"]
    if token.get("access_token"):
        return token["access_token"]
    return None

def extract_text_from_pdf(path: str) -> str:
    text = ""
    if pdfplumber:
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
        except Exception:
            text = ""
    if not text and PdfReader:
        try:
            reader = PdfReader(path)
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"
        except Exception:
            pass
    return text.strip()

def find_or_guess_car(company: Company, parsed: dict):
    qs = Car.objects.filter(company=company)
    lp = parsed.get("license_plate") or ""
    if lp:
        car = qs.filter(license_plate__iexact=lp).first()
        if car:
            return car
    brand = parsed.get("brand") or ""
    model = parsed.get("model") or ""
    category = parsed.get("category") or ""
    if brand and model:
        q = qs.filter(brand__iexact=brand, model__iexact=model)
        if category:
            q = q.filter(category=category)
        car = q.first()
        if car:
            return car
    if category:
        car = qs.filter(category=category, is_rented=False).first()
        if car:
            return car
    return qs.filter(is_rented=False).first()

def create_booking_from_parsed(company: Company, parsed: dict, subject: str):
    if not parsed.get("customer_name"):
        raise ValueError("Λείπει 'customer_name' από το PDF.")
    if not parsed.get("start_date") or not parsed.get("end_date"):
        raise ValueError("Λείπουν 'start_date'/'end_date'.")
    car = find_or_guess_car(company, parsed)
    if not car:
        raise ValueError("Δεν βρέθηκε διαθέσιμο όχημα.")
    booking = Booking(
        company=company,
        car=car,
        start_date=parsed["start_date"],
        end_date=parsed["end_date"],
        customer_name=parsed["customer_name"],
        customer_phone=parsed.get("customer_phone", ""),
        extra_insurance=bool(parsed.get("extra_insurance")),
        total_price=parsed.get("total_price") or 0,
        status=Booking.STATUS_REQUESTED,
        created_by=None,
    )
    booking.full_clean()
    booking.save()
    return booking


class Command(BaseCommand):
    help = "Συγχρονίζει emails από Outlook (Graph) και δημιουργεί Bookings από PDF."

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Φίλτρο ανά εταιρεία (Company.email).", default=None)
        parser.add_argument("--top", type=int, default=25, help="Πόσα emails να ελέγξει (default 25).")

    def handle(self, *args, **opts):
        qs = Company.objects.all()
        if opts["company"]:
            qs = qs.filter(email__iexact=opts["company"])
        total_created = total_skipped = total_failed = 0

        for company in qs:
            conn = getattr(company, "outlook_conn", None)
            if not conn:
                self.stdout.write(self.style.WARNING(f"⏭️  {company.name}: δεν έχει OutlookConnection"))
                continue

            token = acquire_token_silent(conn)
            if not token:
                self.stdout.write(self.style.ERROR(f"❌ {company.name}: token έληξε/λείπει. Κάνε ξανά Connect."))
                continue

            headers = {"Authorization": f"Bearer {token}"}
            base_url = "https://graph.microsoft.com/v1.0/me"
            folder_url = f"{base_url}/mailFolders('{OUTLOOK_FOLDER}')/messages"

            filters = ["hasAttachments eq true"]
            if OUTLOOK_FILTER_FROM:
                filters.append(f"from/emailAddress/address eq '{OUTLOOK_FILTER_FROM}'")
            odata_filter = " and ".join(filters)

            params = {
                "$top": str(opts["top"]),
                "$select": "id,subject,receivedDateTime,from",
                "$orderby": "receivedDateTime desc",
                "$filter": odata_filter,
            }

            created = skipped = failed = 0
            try:
                resp = requests.get(folder_url, headers=headers, params=params, timeout=30)
                resp.raise_for_status()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ {company.name}: {e}"))
                continue

            items = resp.json().get("value", [])
            for msg in items:
                mid = msg.get("id")
                subject = msg.get("subject", "")
                received = msg.get("receivedDateTime")
                if ImportedMessage.objects.filter(company=company, message_id=mid).exists():
                    skipped += 1
                    continue

                att_url = f"{base_url}/messages/{mid}/attachments"
                try:
                    att_resp = requests.get(att_url, headers=headers, timeout=30)
                    att_resp.raise_for_status()
                    atts = att_resp.json().get("value", [])
                except Exception as e:
                    ImportedMessage.objects.create(
                        company=company, message_id=mid, subject=subject,
                        received_at=received, status="ERROR", notes=f"attachments: {e}"
                    )
                    failed += 1
                    continue

                pdfs = [a for a in atts
                        if a.get("@odata.type") == "#microsoft.graph.fileAttachment"
                        and (a.get("contentType") or "").lower() in ("application/pdf", "pdf")]
                if not pdfs:
                    ImportedMessage.objects.create(
                        company=company, message_id=mid, subject=subject,
                        received_at=received, status="SKIPPED", notes="no pdf attachments"
                    )
                    skipped += 1
                    continue

                processed_any = False
                for a in pdfs:
                    name = a.get("name") or f"{mid}.pdf"
                    content_bytes = base64.b64decode(a.get("contentBytes") or b"")
                    tmp_path = os.path.join(IMPORT_TMP_DIR, name)
                    try:
                        with open(tmp_path, "wb") as f:
                            f.write(content_bytes)
                        text = extract_text_from_pdf(tmp_path)
                        parsed = parse_united_reservation_text(text)
                        _ = create_booking_from_parsed(company, parsed, subject)
                        created += 1
                        processed_any = True
                    except Exception as e:
                        failed += 1
                        ImportedMessage.objects.create(
                            company=company, message_id=f"{mid}:{name}", subject=subject,
                            received_at=received, status="ERROR", notes=str(e)
                        )
                    finally:
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass

                ImportedMessage.objects.update_or_create(
                    company=company, message_id=mid,
                    defaults={
                        "subject": subject,
                        "received_at": received,
                        "processed_at": timezone.now(),
                        "status": "OK" if processed_any else "SKIPPED",
                        "notes": "" if processed_any else "no parsed bookings",
                    }
                )

            self.stdout.write(self.style.SUCCESS(
                f"✅ {company.name}: created={created}, skipped={skipped}, failed={failed}"
            ))
            total_created += created; total_skipped += skipped; total_failed += failed

        self.stdout.write(self.style.SUCCESS(
            f"📊 TOTAL: created={total_created}, skipped={total_skipped}, failed={total_failed}"
        ))

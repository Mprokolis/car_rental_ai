import email
import imaplib
import os
import re
import sys
import traceback
from email.header import decode_header, make_header
from pathlib import Path
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils.timezone import now

from rentals.models import Company, Booking
from rentals.utils_email import parse_booking_text

DEFAULT_FOLDER = os.environ.get("IMAP_FOLDER", "[Gmail]/All Mail")
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_USER = os.environ.get("IMAP_USER")
IMAP_PASS = os.environ.get("IMAP_PASS")
IMAP_SENDER_FILTER = os.environ.get("IMAP_SENDER_FILTER")  # optional


def _ensure_imap_creds():
    if not IMAP_USER or not IMAP_PASS:
        raise CommandError("IMAP_USER/IMAP_PASS δεν έχουν οριστεί στο περιβάλλον (.env).")


def _connect() -> imaplib.IMAP4_SSL:
    _ensure_imap_creds()
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    M.login(IMAP_USER, IMAP_PASS)
    return M


def _select_folder(M: imaplib.IMAP4_SSL, folder: str):
    typ, _ = M.select(folder, readonly=False)
    if typ != "OK":
        raise CommandError(f"Αδυναμία επιλογής φακέλου: {folder} ({typ})")


def _decode(s: str) -> str:
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return s


def _normalize_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name or "")
    name = name.strip()
    return name or "attachment.pdf"


def _search_query(include_seen: bool, sender: Optional[str], raw_query: Optional[str], gm_raw: Optional[str]):
    if gm_raw:
        return ("gm", gm_raw)  # ειδική διαδρομή με X-GM-RAW
    if raw_query:
        return ("raw", raw_query)
    parts = []
    if sender:
        parts += ['FROM', f'"{sender}"']
    parts += ['ALL'] if include_seen else ['UNSEEN']
    return ("std", " ".join(parts) or "ALL")


def _extract_x_gm_msgid(M: imaplib.IMAP4_SSL, uid: str) -> Optional[str]:
    try:
        typ, data = M.uid('fetch', uid, '(X-GM-MSGID)')
        if typ == 'OK' and data and data[0]:
            payload = data[0]
            if isinstance(payload, tuple):
                payload = payload[1]
            if isinstance(payload, bytes):
                payload = payload.decode(errors='ignore')
            m = re.search(r'X-GM-MSGID\s+\((\d+)\)', payload) or re.search(r'X-GM-MSGID\s+(\d+)', payload)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def _save_pdf(company: Company, filename: str, content: bytes) -> str:
    rel_dir = f"bookings/{company.id}/{now().strftime('%Y/%m/%d')}/"
    base_path = Path(settings.MEDIA_ROOT) / rel_dir
    base_path.mkdir(parents=True, exist_ok=True)

    safe_name = _normalize_filename(filename)
    full_rel = rel_dir + safe_name
    full_abs = base_path / safe_name

    counter = 1
    while full_abs.exists():
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        safe_name = f"{stem}_{counter}{suffix}"
        full_rel = rel_dir + safe_name
        full_abs = base_path / safe_name
        counter += 1

    with open(full_abs, "wb") as f:
        f.write(content)
    return full_rel


def _parse_pdf_bytes(pdf_bytes: bytes) -> dict:
    from io import BytesIO
    try:
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(BytesIO(pdf_bytes)) or ""
        except Exception:
            text = ""
        return parse_booking_text(text)
    except Exception:
        return {}


class Command(BaseCommand):
    help = "Εισαγωγή κρατήσεων από email (IMAP) με parsing PDF, dedupe (X-GM-MSGID/UID) και προαιρετικό auto-convert."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Όνομα εταιρείας (Company.name).")
        parser.add_argument("--folder", default=DEFAULT_FOLDER, help="IMAP φάκελος (π.χ. [Gmail]/All Mail).")
        parser.add_argument("--include-seen", action="store_true", help="Συμπερίληψη SEEN.")
        parser.add_argument("--no-include-seen", dest="include_seen", action="store_false")
        parser.set_defaults(include_seen=True)

        parser.add_argument("--sender", default=IMAP_SENDER_FILTER, help="Φίλτρο αποστολέα (FROM:).")
        parser.add_argument("--raw-query", default=None, help="Ωμή IMAP query (SEARCH).")
        parser.add_argument("--gm-raw", default=None, help="Gmail RAW (X-GM-RAW).")
        parser.add_argument("--mark-seen", action="store_true", help="Σημάδεψε ως SEEN αφού εισαχθούν.")
        parser.add_argument("--auto-convert", action="store_true",
                            help="Μετά το import, δημιουργεί αυτόματα RentalRequest & RentalDecision και αλλάζει status=active.")

    def handle(self, *args, **opts):
        company_name = opts["company"]
        folder = opts["folder"]
        include_seen = opts["include_seen"]
        sender = opts["sender"]
        raw_query = opts["raw_query"]
        gm_raw = opts["gm_raw"]
        mark_seen = opts["mark_seen"]
        auto_convert = opts["auto_convert"]

        company = Company.objects.filter(name__iexact=company_name).first()
        if not company:
            raise CommandError(f"Δεν βρέθηκε Company με name='{company_name}'")

        try:
            M = _connect()
        except Exception as e:
            raise CommandError(f"IMAP σύνδεση απέτυχε: {e}")

        try:
            _select_folder(M, folder)
        except Exception:
            M.logout()
            raise

        try:
            mode, query = _search_query(include_seen, sender, raw_query, gm_raw)
            if mode == "gm":
                typ, data = M.uid("search", "X-GM-RAW", query)
            elif mode == "raw":
                typ, data = M.search(None, *query.split())
            else:
                typ, data = M.search(None, *query.split())
            if typ != "OK":
                raise CommandError(f"IMAP search error: {typ}")
            uids = data[0].split()
        except Exception as e:
            M.logout()
            raise CommandError(f"Αποτυχία στο search: {e}")

        imported, skipped, converted, errors = 0, 0, 0, 0

        for uid in uids:
            uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)

            try:
                gm_msgid = _extract_x_gm_msgid(M, uid_str)

                qs = Booking.objects.filter(company=company)
                if gm_msgid:
                    if qs.filter(gm_msgid=str(gm_msgid)).exists():
                        skipped += 1
                        continue
                else:
                    if qs.filter(source_email_uid=str(uid_str)).exists():
                        skipped += 1
                        continue

                typ, fetched = M.uid("fetch", uid_str, "(BODY.PEEK[] UID X-GM-MSGID)")
                if typ != "OK" or not fetched or not fetched[0]:
                    skipped += 1
                    continue

                raw = fetched[0][1] if isinstance(fetched[0], tuple) else fetched[0]
                if isinstance(raw, bytes):
                    msg = email.message_from_bytes(raw)
                else:
                    msg = email.message_from_string(raw)

                from_hdr = _decode(msg.get("From", ""))
                # extra έλεγχος αποστολέα, αν δόθηκε
@@ -219,52 +219,53 @@ class Command(BaseCommand):
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    cdisp = part.get("Content-Disposition", "")
                    ctype = part.get_content_type()
                    if "attachment" in cdisp or ctype == "application/pdf":
                        filename = part.get_filename() or "attachment.pdf"
                        filename = _decode(filename)
                        payload = part.get_payload(decode=True) or b""
                        if not payload:
                            continue
                        pdf_rel_path = _save_pdf(company, filename, payload)
                        pdf_found = True
                        parsed = _parse_pdf_bytes(payload)
                        break

                if not pdf_found:
                    skipped += 1
                    continue

                booking = Booking.objects.create(
                    company=company,
                    customer_name=parsed.get("customer_name", "") or "",
                    customer_email=parsed.get("customer_email", "") or "",
                    customer_phone=parsed.get("customer_phone", "") or "",
                    booking_code=parsed.get("booking_code", "") or "",
                    start_at=parsed.get("start_at"),
                    end_at=parsed.get("end_at"),
                    total_price=parsed.get("total_price"),
                    requested_category=parsed.get("requested_category", "") or "",
                    extra_insurance=bool(parsed.get("extra_insurance", False)),
                    status="imported",
                    source_email_uid=str(uid_str or ""),
                    gm_msgid=str(gm_msgid or ""),
                    raw_pdf_path=pdf_rel_path,
                )
                imported += 1

                if auto_convert:
                    # δημιουργία RentalRequest & RentalDecision, update status
                    try:
                        rr, dec = booking.to_rental_request()
                        booking.status = "active"
                        booking.save(update_fields=["status"])
                        converted += 1
                    except Exception:
                        errors += 1

                if mark_seen:
                    try:
                        M.uid("store", uid_str, "+FLAGS", "(\\Seen)")
                    except Exception:
                        pass
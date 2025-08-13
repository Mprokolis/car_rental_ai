from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse, HttpResponseBadRequest
from django.core.mail import send_mail
from django.db.models import Q
from django.conf import settings
from django.utils import timezone

from .forms import (
    CarForm,
    CarSelectionForm,
    CompanyLoginForm,
    CompanyRegistrationForm,
    BookingForm,
    BookingFilterForm,
)
from .models import Car, Company, Booking, OutlookConnection, ImportedMessage
from .utils import rank_cars
from recommendations.models import RentalDecision, RentalRequest

# ---- United parser (relative import) ----
from .parsers.united_pdf import parse_united_reservation_text

# ---------------- Outlook / Graph imports ----------------
import os, json, base64, tempfile, datetime
import requests

try:
    import msal
except ImportError:
    msal = None

# Προσπαθούμε πρώτα με pdfplumber (καλύτερο για text extraction),
# αλλιώς πέφτουμε σε PyPDF2.
try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None


# ---------------- Βοηθητικά για MSAL/Graph ----------------

GRAPH_SCOPES = getattr(settings, "MS_GRAPH_SCOPES", ["offline_access", "Mail.Read"])
MS_CLIENT_ID = getattr(settings, "MS_GRAPH_CLIENT_ID", None)
MS_CLIENT_SECRET = getattr(settings, "MS_GRAPH_CLIENT_SECRET", None)
MS_TENANT = getattr(settings, "MS_GRAPH_TENANT", "common")
MS_REDIRECT = getattr(settings, "MS_GRAPH_REDIRECT_URI", "http://localhost:8000/integrations/outlook/callback/")

OUTLOOK_FILTER_FROM = getattr(settings, "OUTLOOK_FILTER_FROM", "")
OUTLOOK_FOLDER = getattr(settings, "OUTLOOK_FOLDER", "Inbox")
IMPORT_TMP_DIR = getattr(settings, "IMPORT_TMP_DIR", os.path.join(os.getcwd(), "tmp_imports"))
os.makedirs(IMPORT_TMP_DIR, exist_ok=True)

def _msal_app():
    """Φτιάχνει μια ConfidentialClientApplication για OAuth code flow."""
    if not msal:
        raise RuntimeError("Το πακέτο msal δεν είναι εγκατεστημένο. pip install msal")
    if not MS_CLIENT_ID or not MS_CLIENT_SECRET:
        raise RuntimeError("Ρύθμισε MS_GRAPH_CLIENT_ID / MS_GRAPH_CLIENT_SECRET στα settings/env.")
    authority = f"https://login.microsoftonline.com/{MS_TENANT}"
    return msal.ConfidentialClientApplication(
        MS_CLIENT_ID,
        authority=authority,
        client_credential=MS_CLIENT_SECRET,
    )

def _get_auth_url():
    app = _msal_app()
    return app.get_authorization_request_url(GRAPH_SCOPES, redirect_uri=MS_REDIRECT, prompt="select_account")

def _acquire_token_by_code(auth_code: str):
    app = _msal_app()
    result = app.acquire_token_by_authorization_code(auth_code, scopes=GRAPH_SCOPES, redirect_uri=MS_REDIRECT)
    if "access_token" not in result:
        raise RuntimeError(f"Acquire token failed: {result}")
    return result

def _acquire_token_silent(conn: OutlookConnection):
    """Προσπάθεια για silent refresh με refresh_token."""
    app = _msal_app()
    token = conn.token_json or {}
    accounts = app.get_accounts(username=conn.account_upn) if conn.account_upn else []
    result = None
    if accounts:
        result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
    if not result and token.get("refresh_token"):
        result = app.acquire_token_by_refresh_token(token["refresh_token"], scopes=GRAPH_SCOPES)
    if result and "access_token" in result:
        # ενημέρωσε αποθηκευμένα tokens
        conn.token_json = result
        conn.save(update_fields=["token_json", "updated_at"])
        return result["access_token"]
    # μπορεί το access_token να είναι ακόμα έγκυρο στο token_json
    if token.get("access_token") and token.get("expires_in"):
        return token["access_token"]
    return None


# ---------------- PDF parsing ----------------

def _extract_text_from_pdf(path: str) -> str:
    """Επιστρέφει συνεχές κείμενο από PDF. Προσπαθεί pdfplumber → PyPDF2."""
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

def _parse_booking_from_text(txt: str) -> dict:
    # 👇 πλέον κάνουμε delegate στον United parser
    return parse_united_reservation_text(txt)


def _find_or_guess_car(company: Company, parsed: dict):
    """
    Προσπάθεια ταύτισης οχήματος:
    1) με πινακίδα
    2) με brand+model (και προαιρετικά category)
    3) αλλιώς παίρνουμε διαθέσιμο της ίδιας κατηγορίας
    """
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


def _create_booking_from_parsed(company: Company, parsed: dict, subject: str):
    """
    Δημιουργεί Booking από parsed δεδομένα. Αν λείπουν κρίσιμα πεδία, σηκώνει εξαίρεση.
    """
    if not parsed.get("customer_name"):
        raise ValueError("Λείπει 'customer_name' από το PDF.")
    if not parsed.get("start_date") or not parsed.get("end_date"):
        raise ValueError("Λείπουν ημερομηνίες 'start_date' / 'end_date'.")

    car = _find_or_guess_car(company, parsed)
    if not car:
        raise ValueError("Δεν βρέθηκε διαθέσιμο όχημα που να ταιριάζει.")

    booking = Booking(
        company=company,
        car=car,
        start_date=parsed["start_date"],
        end_date=parsed["end_date"],
        customer_name=parsed["customer_name"],
        customer_phone=parsed.get("customer_phone", ""),
        extra_insurance=bool(parsed.get("extra_insurance")),
        total_price=parsed.get("total_price") or 0,
        status=Booking.STATUS_IMPORTED,  # ξεκινά ως imported
        created_by=None,
    )
    booking.full_clean()
    booking.save()
    return booking


# ---------------- Υπάρχουσες Views ----------------

@login_required
def home(request):
    return redirect("rentals:select_car")


def register_company(request):
    form = CompanyRegistrationForm(request.POST or None)
    if form.is_valid():
        user = User.objects.create_user(
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
            email=form.cleaned_data["email"],
        )
        Company.objects.create(
            user=user,
            name=form.cleaned_data["name"],
            email=form.cleaned_data["email"],
        )
        messages.success(request, "Η εταιρεία δημιουργήθηκε! Συνδεθείτε για να συνεχίσετε.")
        return redirect("rentals:login_company")
    return render(request, "rentals/register.html", {"form": form})


def login_company(request):
    form = CompanyLoginForm(request, data=request.POST or None)
    if form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
        )
        if user:
            login(request, user)
            return redirect("rentals:select_car")
        messages.error(request, "Λανθασμένα στοιχεία.")
    return render(request, "rentals/login.html", {"form": form})


def logout_company(request):
    logout(request)
    return redirect("rentals:login_company")


@login_required
def select_car(request):
    form = CarSelectionForm(request.GET or None)
    request_id = None
    chosen_category = None

    company = get_object_or_404(Company, user=request.user)
    base_qs = Car.objects.filter(company=company)
    available_qs = base_qs.filter(is_rented=False)
    rented_qs = base_qs.filter(is_rented=True)

    if form.is_valid():
        chosen_category = form.cleaned_data.get("category")
        days = form.cleaned_data.get("days") or 1
        total_price = form.cleaned_data.get("total_price") or 0
        extra_insurance = form.cleaned_data.get("extra_insurance")

        rental_request = RentalRequest.objects.create(
            company=company,
            days=days,
            total_price=total_price,
            extra_insurance=bool(extra_insurance),
            requested_category=chosen_category or "",
        )
        RentalDecision.objects.create(request=rental_request)
        request_id = rental_request.id

        available_cars = rank_cars(
            {
                "category": chosen_category,
                "days": days,
                "total_price": total_price,
                "extra_insurance": extra_insurance,
            },
            list(available_qs),
            company.id
        )
    else:
        available_cars = available_qs.order_by("brand", "model")

    rented_cars = rented_qs.order_by("brand", "model")

    return render(
        request,
        "rentals/select_car.html",
        {
            "form": form,
            "available_cars": available_cars,
            "rented_cars": rented_cars,
            "request_id": request_id,
        },
    )


@login_required
def add_car(request):
    form = CarForm(request.POST or None)
    if form.is_valid():
        car = form.save(commit=False)
        car.company = get_object_or_404(Company, user=request.user)
        car.save()
        messages.success(request, "Το όχημα προστέθηκε!")
        return redirect("rentals:home")
    return render(request, "rentals/add_car.html", {"form": form})


@login_required
def edit_car(request, car_id: int):
    """Επεξεργασία στοιχείων οχήματος (με διπλό κλικ από τη λίστα)."""
    car = get_object_or_404(Car, id=car_id, company__user=request.user)
    if request.method == "POST":
        form = CarForm(request.POST, instance=car)
        if form.is_valid():
            form.save()
            messages.success(request, "Το όχημα ενημερώθηκε επιτυχώς.")
            return redirect("rentals:select_car")
    else:
        form = CarForm(instance=car)
    return render(request, "rentals/edit_car.html", {"form": form, "car": car})


@login_required
def delete_car(request, car_id):
    car = get_object_or_404(Car, id=car_id, company__user=request.user)
    if request.method == "POST":
        if car.is_rented:
            messages.error(request, "Δεν μπορείς να διαγράψεις όχημα που είναι νοικιασμένο.")
        else:
            car.delete()
            messages.success(request, "Το όχημα διαγράφηκε επιτυχώς.")
        return redirect("rentals:select_car")
    return redirect("rentals:select_car")


@login_required
def delete_cars_view(request):
    company = get_object_or_404(Company, user=request.user)
    cars = Car.objects.filter(company=company, is_rented=False)

    if request.method == "POST":
        selected_ids = request.POST.getlist("selected_cars")
        deleted_count = 0
        for car_id in selected_ids:
            car = cars.filter(id=car_id).first()
            if car:
                car.delete()
                deleted_count += 1
        messages.success(request, f"Διαγράφηκαν {deleted_count} οχήματα.")
        return redirect("rentals:select_car")

    return render(request, "rentals/delete_cars.html", {"cars": cars})


@login_required
def choose_car(request, request_id: int, car_id: int):
    decision = get_object_or_404(
        RentalDecision,
        request__id=request_id,
        request__company__user=request.user,
    )
    chosen_car = get_object_or_404(
        Car,
        id=car_id,
        company__user=request.user,
        is_rented=False,
    )
    chosen_car.is_rented = True
    chosen_car.save(update_fields=["is_rented"])

    decision.chosen_car = chosen_car
    decision.save(update_fields=["chosen_car"])

    messages.success(
        request,
        f"Επιλέχθηκε (και δεσμεύθηκε) το όχημα: {chosen_car.brand} {chosen_car.model}",
    )
    return redirect("rentals:select_car")


@login_required
def return_car(request, car_id: int):
    car = get_object_or_404(Car, id=car_id, company__user=request.user)
    if car.is_rented:
        car.is_rented = False
        car.save(update_fields=["is_rented"])
        messages.success(request, f"Το όχημα {car.brand} {car.model} επεστράφη στα διαθέσιμα.")
    else:
        messages.warning(request, "Αυτό το όχημα δεν είναι νοικιασμένο.")
    return redirect("rentals:select_car")


@login_required
def fleet_status(request):
    available_cars = (
        Car.objects.filter(company__user=request.user, is_rented=False).order_by("brand", "model")
    )
    rented_cars = (
        Car.objects.filter(company__user=request.user, is_rented=True).order_by("brand", "model")
    )
    return render(
        request,
        "rentals/fleet_status.html",
        {"available_cars": available_cars, "rented_cars": rented_cars},
    )


def test_email(request):
    send_mail(
        subject="📧 Δοκιμαστικό Email από Django",
        message="Αυτό είναι ένα δοκιμαστικό email για να ελέγξουμε αν λειτουργεί η αποστολή.",
        from_email=None,
        recipient_list=["nikfragia06@gmail.com"],
        fail_silently=False,
    )
    return HttpResponse("✅ Το email στάλθηκε!")


# ---------------- Bookings ----------------

@login_required
def bookings_list(request):
    company = get_object_or_404(Company, user=request.user)

    # POST: μαζική διαγραφή επιλεγμένων
    if request.method == "POST" and request.POST.get("action") == "delete_selected":
        selected_ids = request.POST.getlist("selected_bookings")
        if not selected_ids:
            messages.info(request, "Δεν επέλεξες καμία κράτηση.")
            return redirect("rentals:bookings_list")

        qs_del = Booking.objects.filter(company=company, id__in=selected_ids).select_related("car")
        deleted = 0
        for b in qs_del:
            # Αν (κακώς) διαγραφεί ενεργή, αποδέσμευσε το όχημα για ασφάλεια
            if b.status == Booking.STATUS_ACTIVE and b.car and b.car.is_rented:
                b.car.is_rented = False
                b.car.save(update_fields=["is_rented"])
            b.delete()
            deleted += 1

        messages.success(request, f"Διαγράφηκαν {deleted} κρατήσεις.")
        return redirect("rentals:bookings_list")

    # GET: φίλτρα + λίστα
    qs = Booking.objects.filter(company=company).select_related("car")
    f = BookingFilterForm(request.GET or None)
    if f.is_valid():
        status = f.cleaned_data.get("status")
        start_from = f.cleaned_data.get("start_from")
        end_to = f.cleaned_data.get("end_to")
        if status:
            qs = qs.filter(status=status)
        if start_from:
            qs = qs.filter(end_date__gte=start_from)
        if end_to:
            qs = qs.filter(start_date__lte=end_to)

    bookings = qs.order_by("-start_date", "-id")
    return render(request, "rentals/bookings_list.html", {"bookings": bookings, "filter_form": f})


@login_required
def booking_create(request):
    company = get_object_or_404(Company, user=request.user)
    form = BookingForm(requestPOST_or_None := request.POST or None, company=company)
    if form.is_valid():
        booking = form.save(commit=False)
        booking.company = company
        booking.created_by = request.user
        booking.status = Booking.STATUS_IMPORTED
        booking.full_clean()
        booking.save()
        messages.success(request, "Η εισαγόμενη κράτηση δημιουργήθηκε.")
        return redirect("rentals:bookings_list")
    return render(request, "rentals/booking_form.html", {"form": form})


def _has_conflict(b: Booking) -> bool:
    return Booking.objects.filter(
        car=b.car,
        status__in=[Booking.STATUS_ACTIVE],
    ).exclude(pk=b.pk).filter(
        end_date__gte=b.start_date, start_date__lte=b.end_date
    ).exists()


@login_required
def booking_confirm(request, pk: int):
    """
    Δεν χρησιμοποιείται πλέον στάδιο 'confirm' (καταργήθηκε).
    Κρατάμε τη view για συμβατότητα και ενημερώνουμε τον χρήστη.
    """
    messages.info(request, "Το στάδιο 'confirm' δεν χρησιμοποιείται πλέον. Χρησιμοποίησε 'Start' για ενεργοποίηση.")
    return redirect("rentals:bookings_list")


@login_required
def booking_start(request, pk: int):
    company = get_object_or_404(Company, user=request.user)
    booking = get_object_or_404(Booking, pk=pk, company=company)
    booking.status = Booking.STATUS_ACTIVE
    if _has_conflict(booking):
        messages.error(request, "Δεν γίνεται έναρξη: υπάρχει σύγκρουση με άλλη ενεργή κράτηση.")
        return redirect("rentals:bookings_list")

    booking.save(update_fields=["status", "updated_at"])
    if not booking.car.is_rented:
        booking.car.is_rented = True
        booking.car.save(update_fields=["is_rented"])
    messages.success(request, "Η κράτηση ξεκίνησε και το όχημα δεσμεύτηκε.")
    return redirect("rentals:bookings_list")


@login_required
def booking_complete(request, pk: int):
    company = get_object_or_404(Company, user=request.user)
    booking = get_object_or_404(Booking, pk=pk, company=company)
    booking.status = Booking.STATUS_COMPLETED
    booking.save(update_fields=["status", "updated_at"])
    if booking.car.is_rented:
        booking.car.is_rented = False
        booking.car.save(update_fields=["is_rented"])
    messages.success(request, "Η κράτηση ολοκληρώθηκε και το όχημα αποδεσμεύτηκε.")
    return redirect("rentals:bookings_list")


@login_required
def booking_cancel(request, pk: int):
    company = get_object_or_404(Company, user=request.user)
    booking = get_object_or_404(Booking, pk=pk, company=company)
    was_active = booking.status == Booking.STATUS_ACTIVE
    booking.status = Booking.STATUS_CANCELLED
    booking.save(update_fields=["status", "updated_at"])
    if was_active and booking.car.is_rented:
        booking.car.is_rented = False
        booking.car.save(update_fields=["is_rented"])
    messages.success(request, "Η κράτηση ακυρώθηκε.")
    return redirect("rentals:bookings_list")


# ---------------- Outlook Integration ----------------

@login_required
def connect_outlook(request):
    """Ξεκινά το OAuth flow στο Microsoft 365."""
    company = get_object_or_404(Company, user=request.user)
    try:
        auth_url = _get_auth_url()
    except Exception as e:
        return HttpResponseBadRequest(f"Σφάλμα ρύθμισης MSAL/Graph: {e}")
    # Θα επιστρέψει στο outlook_callback
    request.session["connect_outlook_company_id"] = company.id
    return redirect(auth_url)


@login_required
def outlook_callback(request):
    """Δέχεται το authorization code από την Microsoft και αποθηκεύει tokens."""
    company_id = request.session.pop("connect_outlook_company_id", None)
    if not company_id:
        return HttpResponseBadRequest("Λείπει company από το session.")
    company = get_object_or_404(Company, id=company_id, user=request.user)

    code = request.GET.get("code")
    if not code:
        error = request.GET.get("error_description") or request.GET.get("error") or "No code"
        messages.error(request, f"Αποτυχία σύνδεσης Outlook: {error}")
        return redirect("rentals:bookings_list")

    try:
        token_result = _acquire_token_by_code(code)
    except Exception as e:
        messages.error(request, f"Αποτυχία token exchange: {e}")
        return redirect("rentals:bookings_list")

    upn = token_result.get("id_token_claims", {}).get("preferred_username") or company.email
    conn, created = OutlookConnection.objects.get_or_create(company=company, defaults={
        "account_upn": upn,
        "token_json": token_result,
    })
    if not created:
        conn.account_upn = upn
        conn.token_json = token_result
        conn.save(update_fields=["account_upn", "token_json", "updated_at"])

    messages.success(request, "✅ Το Outlook συνδέθηκε επιτυχώς! Μπορείς τώρα να κάνεις Sync.")
    return redirect("rentals:bookings_list")


@login_required
def outlook_sync(request):
    """
    Τραβά νέες αναγνώσεις emails από το Inbox (με φίλτρο αποστολέα προαιρετικά),
    κατεβάζει PDF συνημμένα, κάνει parsing και δημιουργεί Booking entries.
    Κρατά ImportedMessage για να μη διπλοπερνάει μηνύματα.
    """
    company = get_object_or_404(Company, user=request.user)
    conn = getattr(company, "outlook_conn", None)
    if not conn:
        messages.error(request, "Πρώτα σύνδεσε Outlook (Connect) από το μενού.")
        return redirect("rentals:bookings_list")

    access_token = _acquire_token_silent(conn)
    if not access_token:
        messages.error(request, "Το token έληξε. Ξανασύνδεσε Outlook.")
        return redirect("rentals:bookings_list")

    headers = {"Authorization": f"Bearer {access_token}"}
    # Βασικό filter: μόνο με συνημμένα, προαιρετικά από συγκεκριμένο αποστολέα
    base_url = "https://graph.microsoft.com/v1.0/me"
    # Πλοήγηση στον φάκελο
    folder_url = f"{base_url}/mailFolders('{OUTLOOK_FOLDER}')/messages"
    # Σύνθεση $filter
    filters = ["hasAttachments eq true"]
    if OUTLOOK_FILTER_FROM:
        # Graph OData filter για from/emailAddress/address
        filters.append(f"from/emailAddress/address eq '{OUTLOOK_FILTER_FROM}'")
    odata_filter = " and ".join(filters)

    params = {
        "$top": "25",
        "$select": "id,subject,receivedDateTime,from",
        "$orderby": "receivedDateTime desc",
        "$filter": odata_filter,
    }

    created, skipped, failed = 0, 0, 0

    try:
        resp = requests.get(folder_url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        messages.error(request, f"Σφάλμα ανάγνωσης inbox: {e}")
        return redirect("rentals:bookings_list")

    data = resp.json()
    items = data.get("value", [])

    for msg in items:
        msg_id = msg.get("id")
        subject = msg.get("subject", "")
        received = msg.get("receivedDateTime")
        if ImportedMessage.objects.filter(company=company, message_id=msg_id).exists():
            skipped += 1
            continue

        # Πάρε τα attachments του συγκεκριμένου μηνύματος
        att_url = f"{base_url}/messages/{msg_id}/attachments"
        try:
            att_resp = requests.get(att_url, headers=headers, params={"$select": "name,contentType,contentBytes,@odata.type"}, timeout=30)
            att_resp.raise_for_status()
            atts = att_resp.json().get("value", [])
        except Exception as e:
            ImportedMessage.objects.create(
                company=company, message_id=msg_id, subject=subject,
                received_at=received, status="ERROR", notes=f"attachments: {e}"
            )
            failed += 1
            continue

        # Φιλτράρουμε μόνο PDF fileAttachment
        pdf_attachments = [a for a in atts
                           if a.get("@odata.type") == "#microsoft.graph.fileAttachment"
                           and (a.get("contentType") or "").lower() in ("application/pdf", "pdf")]

        if not pdf_attachments:
            ImportedMessage.objects.create(
                company=company, message_id=msg_id, subject=subject,
                received_at=received, status="SKIPPED", notes="no pdf attachments"
            )
            skipped += 1
            continue

        processed_any = False
        for a in pdf_attachments:
            name = a.get("name") or f"{msg_id}.pdf"
            content_bytes = base64.b64decode(a.get("contentBytes") or b"")
            tmp_path = os.path.join(IMPORT_TMP_DIR, name)
            try:
                with open(tmp_path, "wb") as f:
                    f.write(content_bytes)
                # Parse PDF
                text = _extract_text_from_pdf(tmp_path)
                parsed = _parse_booking_from_text(text)
                _ = _create_booking_from_parsed(company, parsed, subject)
                processed_any = True
                created += 1
            except Exception as e:
                failed += 1
                ImportedMessage.objects.create(
                    company=company, message_id=f"{msg_id}:{name}", subject=subject,
                    received_at=received, status="ERROR", notes=str(e)
                )
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        ImportedMessage.objects.update_or_create(
            company=company, message_id=msg_id,
            defaults={
                "subject": subject,
                "received_at": received,
                "processed_at": timezone.now(),
                "status": "OK" if processed_any else "SKIPPED",
                "notes": "" if processed_any else "no parsed bookings",
            }
        )

    messages.success(request, f"Outlook Sync: ✅ created={created}, ⏭️ skipped={skipped}, ❌ failed={failed}")
    return redirect("rentals:bookings_list")

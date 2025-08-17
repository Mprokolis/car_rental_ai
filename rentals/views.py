from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse, HttpResponseNotAllowed
from django.core.mail import send_mail

from .forms import (
    CarForm,
    CarSelectionForm,
    CompanyLoginForm,
    CompanyRegistrationForm,
)
from .models import Car, Company, Booking
from .utils import rank_cars
from recommendations.models import RentalDecision, RentalRequest

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


# ---------------- Λίστα κρατήσεων ----------------

@login_required
def bookings_list(request):
    company = get_object_or_404(Company, user=request.user)
    q = Booking.objects.filter(company=company).order_by("start_date")
    status = request.GET.get("status")
    if status:
        q = q.filter(status=status)
    return render(request, "rentals/bookings_list.html", {"bookings": q, "status": status})


@login_required
def booking_set_status(request, booking_id: int, action: str):
    """Αλλάζει status κράτησης με ασφάλεια. Επιτρεπτά actions: activate, complete, cancel, no_show."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    company = get_object_or_404(Company, user=request.user)
    booking = get_object_or_404(Booking, id=booking_id, company=company)

    mapping = {
        "activate": "active",
        "complete": "completed",
        "cancel": "cancelled",
        "no_show": "cancelled",  # προς το παρόν το μετράμε ως cancelled
    }
    if action not in mapping:
        messages.error(request, "Μη έγκυρη ενέργεια.")
    else:
        new_status = mapping[action]
        if booking.status != new_status:
            booking.status = new_status
            booking.save(update_fields=["status"])
        label = "No‑Show" if action == "no_show" else new_status
        messages.success(request, f"Η κράτηση #{booking.id} σημάνθηκε ως {label}.")

    # Επιστροφή στη λίστα, διατηρώντας το φίλτρο
    status_filter = request.POST.get("status_filter", "")
    if status_filter:
        return redirect(f"/rentals/bookings/?status={status_filter}")
    return redirect("rentals:bookings_list")

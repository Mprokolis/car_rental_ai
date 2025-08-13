# rentals/services/bookings.py
from __future__ import annotations
from typing import Dict, Any, Optional, Tuple, List
from decimal import Decimal
from django.db import transaction
from django.db.models import Q

from rentals.models import Company, Booking, Car  # Car/Booking είναι τα ΔΙΚΑ σου μοντέλα

def _as_decimal(x: Any) -> Optional[Decimal]:
    if x is None or x == "":
        return None
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except Exception:
        return None

def _split_brand_model_from_desc(desc: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Π.χ. "Fiat 500 or similar" -> ("Fiat", "500")
    """
    if not desc:
        return None, None
    parts = desc.split()
    if not parts:
        return None, None
    brand = parts[0]
    model = None
    if len(parts) > 1:
        # Σταμάτα πριν από "or" αν υπάρχει
        cutoff = len(parts)
        for i, p in enumerate(parts[1:], start=1):
            if p.lower() == "or":
                cutoff = i
                break
        model = " ".join(parts[1:cutoff]).strip() or None
    return brand, model

_ACRISS_CLASS_MAP = {
    # Απλοποιημένη χαρτογράφηση ACRISS (1ο γράμμα)
    "M": "Mini",
    "N": "Mini",         # Mini Elite -> Mini
    "E": "Economy",
    "C": "Compact",
    "I": "Intermediate",
    "S": "Standard",
    "F": "Fullsize",
    "P": "Premium",
    "L": "Luxury",
    "X": "SUV",          # Special/SUV -> SUV
}

def _category_from_vehicle_class(vehicle_class: Optional[str]) -> Optional[str]:
    if not vehicle_class:
        return None
    first = vehicle_class.strip().upper()[:1]
    return _ACRISS_CLASS_MAP.get(first)

def _resolve_car(company: Company, data: Dict[str, Any]) -> Car:
    """
    Προσπάθησε να βρεις ΚΑΘΑΡΑ ένα διαθέσιμο Car για την εταιρεία.
    Προτεραιότητα:
      1) Με βάση brand+model από "Car: Fiat 500 or similar"
      2) Με βάση category από ACRISS (MBMR -> "Mini", κ.λπ.)
      3) Αν υπάρχει ακριβώς ΕΝΑ διαθέσιμο αυτοκίνητο, πάρε αυτό.
    Αν δεν βρεθεί σαφές match -> ρίξε ValueError με προτάσεις.
    """
    car_desc = (data.get("car_description") or "").strip()
    vehicle_class = (data.get("vehicle_class") or "").strip()
    brand, model = _split_brand_model_from_desc(car_desc)
    qs = Car.objects.filter(company=company, is_rented=False)

    # 1) Brand+Model match
    candidates: List[Car] = []
    if brand:
        q = Q(brand__icontains=brand)
        if model:
            q &= Q(model__icontains=model)
        candidates = list(qs.filter(q))
        if len(candidates) == 1:
            return candidates[0]
        # Αν πολλαπλά, δοκίμασε πιο αυστηρό (ίσο) αν έχει νόημα
        if len(candidates) > 1 and model:
            strict = list(qs.filter(brand__iexact=brand, model__iexact=model))
            if len(strict) == 1:
                return strict[0]

    # 2) Category από ACRISS
    cat = _category_from_vehicle_class(vehicle_class)
    if cat:
        cat_matches = list(qs.filter(category__icontains=cat))
        if len(cat_matches) == 1:
            return cat_matches[0]

    # 3) Μοναδικό διαθέσιμο
    only_one = list(qs[:2])
    if len(only_one) == 1:
        return only_one[0]

    # Δεν βρέθηκε σαφές match -> φτιάξε μήνυμα με προτάσεις
    suggestions = list(qs.values_list("brand", "model", "category", "license_plate"))
    hint_lines = [
        f"- {b} {m} [{c}] ({lp})" for (b, m, c, lp) in suggestions[:8]
    ]
    hint = "\n".join(hint_lines) if hint_lines else "— (κανένα διαθέσιμο)"
    raise ValueError(
        "Δεν μπόρεσα να αντιστοιχίσω αυτοκίνητο (car_id είναι NOT NULL στο Booking).\n"
        f"Πληροφορίες εισαγωγής: car_description='{car_desc}', vehicle_class='{vehicle_class}'.\n"
        "Διαθέσιμα για την εταιρεία τώρα:\n" + hint
    )

@transaction.atomic
def get_or_create_booking_from_united_text(
    data: Dict[str, Any], *, company: Company, created_by=None
):
    """
    Δημιουργεί ή βρίσκει Booking με βάση τα ΔΙΚΑ σου πεδία:
      - car (απαραίτητο), customer_name, customer_phone, start_date, end_date, total_price, extra_insurance
    Dedup κλειδί: (company, customer_name, start_date, end_date, total_price)
    """

    # Όνομα πελάτη
    customer_name = (
        data.get("renter_full_name")
        or " ".join([p for p in [data.get("first_name"), data.get("last_name")] if p])
        or None
    )
    customer_phone = data.get("phone") or None

    # Ημερομηνίες από τον parser (datetime.date)
    start_date = data.get("pickup_date")
    end_date = data.get("return_date")

    total_price = _as_decimal(data.get("total"))

    # Το email δεν δίνει extra_insurance -> False για NOT NULL
    extra_insurance = False

    # created_by (αν χρειάζεται)
    if created_by is None:
        try:
            created_by = company.user
        except Exception:
            created_by = None

    # Υποχρεωτικά για dedup/get_or_create
    if not (customer_name and start_date and end_date and total_price is not None):
        raise ValueError(
            "Λείπουν βασικά πεδία για δημιουργία Booking (name/start/end/total)."
        )

    # Βρες αυτοκίνητο (απαραίτητο γιατί car_id είναι NOT NULL)
    car = _resolve_car(company, data)

    lookup = dict(
        company=company,
        customer_name=customer_name,
        start_date=start_date,
        end_date=end_date,
        total_price=total_price,
    )

    defaults = dict(
        car=car,
        customer_phone=customer_phone,
        extra_insurance=extra_insurance,
        **({"created_by": created_by} if created_by is not None else {}),
    )

    booking, created = Booking.objects.get_or_create(
        **lookup,
        defaults=defaults,
    )

    # Αν υπήρχε ήδη, μπορεί να ενημερώσουμε car/τηλέφωνο
    changed = False
    if not created:
        # Αν το υπάρχον δεν έχει car (θεωρητικά δεν γίνεται λόγω NOT NULL, αλλά για ασφάλεια)
        if getattr(booking, "car_id", None) is None:
            booking.car = car
            changed = True
        # Αν αλλάζει τηλέφωνο
        if customer_phone and booking.customer_phone != customer_phone:
            booking.customer_phone = customer_phone
            changed = True
        # Αν για ιστορικούς λόγους το extra_insurance ήταν null (σε παλιά βάση), βάλ’ το False
        if getattr(booking, "extra_insurance", None) is None:
            booking.extra_insurance = False
            changed = True
        if changed:
            booking.save(update_fields=["car", "customer_phone", "extra_insurance"])

    return booking, created

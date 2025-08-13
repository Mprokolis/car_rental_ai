from __future__ import annotations
import re
from typing import Any, Dict, Optional
from datetime import datetime
from decimal import Decimal, InvalidOperation

DEC_SEP_COMMA = re.compile(r"[^\d,.-]+")

def _clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.strip()
    return s or None

def _normalize(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = "\n".join(line.strip() for line in t.split("\n"))
    return t

def _search(pattern: str, text: str, flags=re.IGNORECASE | re.MULTILINE) -> Optional[str]:
    m = re.search(pattern, text, flags)
    return _clean(m.group(1)) if m else None

def _to_decimal_eu(s: Optional[str]) -> Optional[Decimal]:
    if not s:
        return None
    s = s.strip()
    s_clean = DEC_SEP_COMMA.sub("", s)
    if "," in s_clean and "." in s_clean:
        s_clean = s_clean.replace(".", "")
    s_clean = s_clean.replace(",", ".")
    try:
        return Decimal(s_clean)
    except (InvalidOperation, ValueError):
        return None

def _to_datetime(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    fmts = [
        "%d/%m/%Y %H:%M", "%d/%m/%Y %H.%M", "%d/%m/%Y",
        "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d-%m-%Y %H:%M", "%d-%m-%Y",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            continue
    return None

def _iso_to_date(s: Optional[str]) -> Optional[datetime.date]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None

def parse_united_rental_text(text: str) -> Dict[str, Any]:
    """
    Parser για το κείμενο 'United Rent a Car New Reservation [Confirmed]: ...'
    Επιστρέφει ΟΛΑ τα διαθέσιμα πεδία, αν υπάρχουν.
    """
    # Σημαντικό: re.S για multi-line blocks (DOTALL), ώστε να πιάνονται τα Date μετά τα Code κ.λπ.
    DOTALL = re.IGNORECASE | re.MULTILINE | re.DOTALL
    t = _normalize(text)

    reservation_code = _search(r"New Reservation\s*\[Confirmed\]\s*:\s*([A-Z0-9]+)", t)
    your_ref = _search(r"Your Ref\.\s*([A-Za-z0-9\-]+)", t)
    flight_number = _search(r"Fligth\s*Number\s*\n\s*([A-Za-z0-9\- ]+)", t)
    reservation_date = _search(r"Reservation Date\s*([0-9/:.\- ]{8,})", t)
    rate = _search(r"Rate\s*(.+)", t)

    first_name = _search(r"First Name\s*:\s*([A-Za-zÀ-ÖØ-öø-ÿ' -]+)", t)
    last_name  = _search(r"Last Name\s*:\s*([A-Za-zÀ-ÖØ-öø-ÿ' -]+)", t)
    phone      = _search(r"Phone Number\s*:\s*([0-9 +]+)", t)

    time_mileage = _to_decimal_eu(_search(r"Time&Mileage\s*:\s*([0-9.,]+)", t))
    cdw_inclusive = _to_decimal_eu(_search(r"CDW inclusive\s*:\s*([0-9.,]+)", t))
    tax = _to_decimal_eu(_search(r"Tax\s*:\s*([0-9.,]+)", t))
    total = _to_decimal_eu(_search(r"Total\s*:\s*([0-9.,]+)", t))
    prepaid_amount = _to_decimal_eu(_search(r"PrepaidAmount\s*:\s*([0-9.,]+)", t))

    pickup_location_name = _search(r"Pick up Location:\s*Name:\s*([^\n]+)", t)
    pickup_code = _search(r"Pick up Location:.*?\n\s*Code:\s*([A-Z]{3})", t, flags=DOTALL)
    pickup_date_raw = _search(r"Pick up Location:.*?\n.*?\n\s*Date:\s*([0-9/:.\- ]{8,})", t, flags=DOTALL)
    pickup_datetime = _to_datetime(pickup_date_raw)

    return_location_name = _search(r"Return Location:\s*Name:\s*([^\n]+)", t)
    return_code = _search(r"Return Location:.*?\n\s*Code:\s*([A-Z]{3})", t, flags=DOTALL)
    return_date_raw = _search(r"Return Location:.*?\n.*?\n\s*Date:\s*([0-9/:.\- ]{8,})", t, flags=DOTALL)
    return_datetime = _to_datetime(return_date_raw)

    request_source_code = _search(r"Request Source Code\s*:\s*([A-Z0-9]+)", t)
    vehicle_class = _search(r"Vehicle Class\s*:\s*([A-Za-z0-9]+)", t)
    broker = _search(r"Broker\s*:\s*(.+)", t)
    rental_duration_raw = _search(r"Rental Duration\s*:\s*([0-9]+)\s*days?", t)
    car_desc = _search(r"Car\s*:\s*(.+)", t)

    renter_full_name = " ".join([p for p in [first_name, last_name] if p])
    rental_duration_days = int(rental_duration_raw) if rental_duration_raw and rental_duration_raw.isdigit() else None

    # Για ευκολία downstream:
    pickup_date = _iso_to_date(pickup_datetime)
    return_date = _iso_to_date(return_datetime)

    return {
        "supplier": "United Rent a Car",
        "reservation_code": reservation_code,
        "your_reference": your_ref,
        "flight_number": _clean(flight_number),
        "reservation_date": _clean(reservation_date),  # string (π.χ. 2025-08-09)

        "rate": _clean(rate),
        "first_name": _clean(first_name),
        "last_name": _clean(last_name),
        "renter_full_name": _clean(renter_full_name) or None,
        "phone": _clean(phone),

        "time_mileage": time_mileage,
        "cdw_inclusive": cdw_inclusive,
        "tax": tax,
        "total": total,
        "prepaid_amount": prepaid_amount,

        "pickup_location_name": _clean(pickup_location_name),
        "pickup_location_code": _clean(pickup_code),
        "pickup_datetime": _clean(pickup_datetime),
        "pickup_date": pickup_date,  # datetime.date

        "return_location_name": _clean(return_location_name),
        "return_location_code": _clean(return_code),
        "return_datetime": _clean(return_datetime),
        "return_date": return_date,  # datetime.date

        "request_source_code": _clean(request_source_code),
        "vehicle_class": _clean(vehicle_class),
        "broker": _clean(broker),
        "rental_duration_days": rental_duration_days,
        "car_description": _clean(car_desc),
    }

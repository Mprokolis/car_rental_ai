import re
from datetime import datetime
from typing import Dict, Any

DATE_FORMATS = ["%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"]


def parse_date_safe(s: str):
    """Return ``date`` from various formats, ignoring any time component."""
    if not s:
        return None
    s = s.strip()
    if " " in s:
        s = s.split()[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None

def _search(text: str, pattern: str, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None

def parse_booking_text(text: str) -> Dict[str, Any]:
    """
    Απλός parser με regex. Προσαρμόζεις τα patterns στα δικά σου PDFs.
    Επιστρέφει dict με πεδία για Booking.
    """
    t = text.replace('\r', '')
    t = re.sub(r'[ \t]+', ' ', t)

    name = _search(t, r'(?:Name|Customer|Πελάτης)[:\s]+([A-Za-zΑ-Ωα-ω .\'-]+)')
    email = _search(t, r'([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})')
    phone = _search(t, r'(?:Tel(?:ephone)?|Phone(?: Number)?|Τηλ)[:\s]+([\d +()-]{6,})', flags=re.I)

    start_s = _search(t, r'(?:Start|Check\-?in|Έναρξη|Pick\s*up\s*Location.*?Date)[:\s]+([0-9./-]{8,10})', flags=re.I | re.S)
    end_s = _search(t, r'(?:End|Check\-?out|Λήξη|Return\s*Location.*?Date)[:\s]+([0-9./-]{8,10})', flags=re.I | re.S)

    total_s = _search(t, r'(?:Total|Σύνολο|Amount)[:\s]+([0-9]+(?:[.,][0-9]{1,2})?)', flags=re.I)
    category = _search(t, r'(?:Category|Κατηγορία|Vehicle Class)[:\s]+([A-Z0-9]+)', flags=re.I)
    insurance = _search(t, r'(?:Extra Insurance|Έξτρα Ασφάλεια)[:\s]+(Yes|No|Ναι|Όχι)', flags=re.I)
    booking_code = _search(t, r'(?:Request Source Code|Ref(?:erence)?|Reservation)[:\s]+([A-Z0-9-]+)', flags=re.I)

    start_date = parse_date_safe(start_s)
    end_date = parse_date_safe(end_s)

    total_price = None
    if total_s:
        total_s = total_s.replace(',', '.')
        try:
            total_price = float(total_s)
        except Exception:
            total_price = None

    extra_insurance = False
    if insurance:
        extra_insurance = insurance.strip().lower() in ("yes", "ναι", "true")

    requested_category = (category or "").lower()

    return {
        "customer_name": name or "",
        "customer_email": email or "",
        "customer_phone": (phone or "").strip(),
        "start_date": start_date,
        "end_date": end_date,
        "total_price": total_price,
        "requested_category": requested_category,
        "extra_insurance": extra_insurance,
        "booking_code": booking_code or "",
    }

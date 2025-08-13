import re
from datetime import datetime, date

DATE_PATTERNS = [
    r"Start\s*Date[:\s]+(?P<start>\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})",
    r"End\s*Date[:\s]+(?P<end>\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})",
    r"Pickup\s*[:\s]+(?P<start>\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})",
    r"Dropoff\s*[:\s]+(?P<end>\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})",
]

def _parse_date(s: str) -> date | None:
    s = s.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None

def parse_united_reservation_text(txt: str) -> dict:
    """
    Επιστρέφει μόνο τα χρήσιμα:
    - customer_name
    - customer_phone (optional)
    - start_date, end_date
    - brand, model (optional)
    - category (optional: 'small'/'medium'/'compact')
    - license_plate (optional)
    - total_price (optional float)
    - extra_insurance (bool)
    """
    text = (txt or "").strip()

    # Όνομα πελάτη
    customer_name = None
    m = re.search(r"Customer\s*Name[:\s]+(.+)", text, re.IGNORECASE)
    if m:
        customer_name = m.group(1).strip()
    if not customer_name:
        m = re.search(r"Passenger[:\s]+(.+)", text, re.IGNORECASE)
        if m:
            customer_name = m.group(1).strip()

    # Τηλέφωνο (simple)
    customer_phone = None
    m = re.search(r"Phone[:\s]+([\d\+\-\s]+)", text, re.IGNORECASE)
    if m:
        customer_phone = m.group(1).strip()

    # Ημερομηνίες
    start_date = None
    end_date = None
    # προσπαθούμε με αρκετά patterns
    for pat in DATE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m and "start" in m.groupdict():
            d = _parse_date(m.group("start"))
            if d:
                start_date = d
        if m and "end" in m.groupdict():
            d = _parse_date(m.group("end"))
            if d:
                end_date = d

    # fallback: γραμμή με δύο ημερομηνίες τύπου 16-08-2025 to 24-08-2025
    if not start_date or not end_date:
        m = re.search(r"(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})\s*(?:to|–|-|→)\s*(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})", text)
        if m:
            s, e = _parse_date(m.group(1)), _parse_date(m.group(2))
            start_date = start_date or s
            end_date = end_date or e

    # Brand / Model (χαλαρά)
    brand = None
    model = None
    m = re.search(r"Vehicle[:\s]+([A-Za-z]+)\s+([A-Za-z0-9\-]+)", text, re.IGNORECASE)
    if m:
        brand = m.group(1).strip()
        model = m.group(2).strip()

    # Κατηγορία / ACRISS
    category = None
    m = re.search(r"ACRISS[:\s]+([A-Z]{4})", text)
    if m:
        acriss = m.group(1)
        # πολύ απλός χάρτης → τον προσαρμόζεις
        lead = acriss[0]
        category = {"M": "small", "E": "small", "C": "compact", "D": "medium", "I": "medium"}.get(lead)

    # Πινακίδα (αν υπάρχει)
    license_plate = None
    m = re.search(r"(Plate|License)\s*[:\s]+([A-Z0-9\-]+)", text, re.IGNORECASE)
    if m:
        license_plate = m.group(2).strip()

    # Τιμή
    total_price = None
    m = re.search(r"(Total|Amount)\s*[:\s]+([0-9]+(?:[\.,][0-9]{2})?)", text, re.IGNORECASE)
    if m:
        total_price = float(m.group(2).replace(",", "."))

    # Extra Insurance
    extra_insurance = False
    if re.search(r"Extra\s+Insurance\s*[:\s]+(Yes|True|Included)", text, re.IGNORECASE):
        extra_insurance = True

    return {
        "customer_name": customer_name or "",
        "customer_phone": customer_phone or "",
        "start_date": start_date,
        "end_date": end_date,
        "brand": brand or "",
        "model": model or "",
        "category": category or "",
        "license_plate": license_plate or "",
        "total_price": total_price,
        "extra_insurance": extra_insurance,
    }

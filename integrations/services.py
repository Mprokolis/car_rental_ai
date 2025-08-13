import os
import re
from dateutil.parser import parse as parse_dt
from django.conf import settings

# ------------------------------
# Parsing United email body (text)
# ------------------------------
def parse_united_email(subject: str, body_text: str):
    """
    Αναμένει ελεύθερο κείμενο (είτε από Outlook HTML που έγινε text, είτε από mock .txt).
    Παράδειγμα:
      United Booking #U-2025-0001
      Customer: Maria Papadopoulou
      Phone: +30 6912345678
      Start: 09-08-2025
      End: 12-08-2025
      Category: compact
      Extra Insurance: Yes
      Total: 240.00
    """
    text = re.sub(r"\s+", " ", body_text or "").strip()

    def g(pat, default=""):
        m = re.search(pat, text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    booking_ref = g(r"Booking\s*#\s*([A-Za-z0-9\-]+)", "")
    customer_name = g(r"(?:Customer|Name|Πελάτης)\s*:\s*([A-Za-zΆ-ώ .'-]+)", "")
    customer_phone = g(r"(?:Phone|Τηλέφωνο)\s*:\s*([\+\d][\d\s\-\(\)]+)", "")
    start_str = g(r"(?:Start|Έναρξη)\s*:\s*([0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4})", "")
    end_str = g(r"(?:End|Λήξη)\s*:\s*([0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4})", "")
    category = g(r"(?:Category|Κατηγορία)\s*:\s*([A-Za-z]+)", "").lower()
    extra_insurance_str = g(r"(?:Extra Insurance|Έξτρα Ασφάλεια)\s*:\s*(Yes|No|Ναι|Όχι)", "")
    total_str = g(r"(?:Total|Σύνολο)\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)", "")

    def to_date(s):
        if not s: return None
        s = s.replace("/", "-")
        try:
            return parse_dt(s, dayfirst=True).date()
        except Exception:
            return None

    def to_bool(s):
        return s.strip().lower() in {"yes", "ναι", "true", "1"} if s else False

    def to_money(s):
        if not s: return 0
        return float(s.replace(",", "."))

    return {
        "booking_ref": booking_ref,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "start_date": to_date(start_str),
        "end_date": to_date(end_str),
        "category": category or None,
        "extra_insurance": to_bool(extra_insurance_str),
        "total_price": to_money(total_str),
        "raw": text[:2000],
        "subject": (subject or "")[:500],
    }

# ------------------------------
# Mock client (χωρίς Outlook)
# Διαβάζει .txt από UNITED_MOCK_DIR και τα επιστρέφει ως "μηνύματα"
# ------------------------------
def fetch_mock_messages():
    base = settings.UNITED_MOCK_DIR
    os.makedirs(base, exist_ok=True)
    msgs = []
    for fname in os.listdir(base):
        if not fname.lower().endswith(".txt"):
            continue
        path = os.path.join(base, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        # πρώτο μη κενό line ως subject
        subject = ""
        for line in content.splitlines():
            if line.strip():
                subject = line.strip()
                break
        msgs.append({
            "id": fname,         # filename ως message_id (μοναδικό)
            "subject": subject or "United Booking",
            "received": None,    # mock δεν έχει timestamp
            "body": content,
        })
    return msgs

# ------------------------------
# Placeholder Outlook (Graph) client — θα το συμπληρώσουμε όταν έχεις creds
# ------------------------------
def fetch_graph_messages(limit=20):
    raise NotImplementedError("Θα ενεργοποιηθεί όταν βάλεις Microsoft Graph credentials και UNITED_USE_MOCK=False.")

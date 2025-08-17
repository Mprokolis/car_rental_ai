import os
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from pdfminer.high_level import extract_text
from rentals.utils_email import parse_booking_text

class Command(BaseCommand):
    help = "Διάβασε ένα PDF κράτησης και εμφάνισε τα πεδία που αναγνώρισε ο parser."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Πλήρης διαδρομή σε PDF αρχείο.")

    def handle(self, *args, **opts):
        pdf_path = opts["file"]
        if not os.path.isfile(pdf_path):
            raise CommandError(f"Το αρχείο δεν βρέθηκε: {pdf_path}")

        self.stdout.write(f"📄 Διαβάζω PDF: {pdf_path}")
        try:
            text = extract_text(pdf_path)
        except Exception as e:
            raise CommandError(f"Αποτυχία ανάγνωσης PDF: {e}")

        payload = parse_booking_text(text)

        self.stdout.write("🧾 Αποτελέσματα parser:")
        for k, v in payload.items():
            self.stdout.write(f"  - {k}: {v!r}")

        self.stdout.write(self.style.SUCCESS("✅ Τέλος."))

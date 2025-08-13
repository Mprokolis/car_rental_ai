from __future__ import annotations
import sys
import json
from django.core.management.base import BaseCommand, CommandParser
from rentals.models import Company
from rentals.parsers.united_rental import parse_united_rental_text
from rentals.services.bookings import get_or_create_booking_from_united_text

class Command(BaseCommand):
    help = "Διάβασε United Rent a Car reservation (plain text) και ΣΩΣΕ Booking για συγκεκριμένη εταιρεία."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("company", help="Το username ή το slug της εταιρείας (π.χ. 'nikos').")
        parser.add_argument(
            "path",
            nargs="?",
            help="Μονοπάτι σε .txt αρχείο. Αν λείπει, διαβάζει από stdin.",
        )

    def handle(self, *args, **options):
        company_key = options["company"]
        path = options.get("path")

        # Βρες εταιρεία (προσαρμόσ' το αν χρειάζεται)
        try:
            company = Company.objects.get(user__username=company_key)
        except Company.DoesNotExist:
            try:
                company = Company.objects.get(slug=company_key)
            except Company.DoesNotExist:
                raise SystemExit(f"Δεν βρέθηκε εταιρεία με username ή slug = '{company_key}'")

        # Διάβασμα κειμένου
        if path:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            self.stdout.write(self.style.NOTICE(
                "Κάνε paste το κείμενο και μετά Ctrl+Z + Enter (Windows) ή Ctrl+D (Linux/Mac):"
            ))
            text = sys.stdin.read()

        data = parse_united_rental_text(text)

        # ΠΕΡΝΑΜΕ created_by=company.user για να αποφύγουμε NOT NULL αν απαιτείται
        created_by = getattr(company, "user", None)

        booking, created = get_or_create_booking_from_united_text(
            data, company=company, created_by=created_by
        )

        payload = {
            "id": booking.id,
            "company_id": booking.company_id,
            "customer_name": booking.customer_name,
            "customer_phone": booking.customer_phone,
            "start_date": str(booking.start_date),
            "end_date": str(booking.end_date),
            "total_price": str(booking.total_price),
            "extra_insurance": bool(getattr(booking, "extra_insurance", False)),
            "created": created,
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        self.stdout.write(self.style.SUCCESS("OK"))

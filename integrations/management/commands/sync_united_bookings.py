from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from rentals.models import Company, Car, Booking
from integrations.models import IntegrationInbound
from integrations.services import fetch_mock_messages, fetch_graph_messages, parse_united_email

class Command(BaseCommand):
    help = "Συγχρονίζει κρατήσεις από United: mock mode (χωρίς Outlook) ή Graph mode (με Outlook)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20, help="Max messages to scan (Graph mode only)")

    def handle(self, *args, **opts):
        use_mock = settings.UNITED_USE_MOCK
        limit = opts["limit"]

        # Βρες την εταιρεία που θα χρεώνεται τις κρατήσεις
        company = None
        if getattr(settings, "UNITED_TARGET_COMPANY_EMAIL", ""):
            company = Company.objects.filter(email=settings.UNITED_TARGET_COMPANY_EMAIL).first()
        if not company:
            company = Company.objects.order_by("id").first()
        if not company:
            self.stderr.write(self.style.ERROR("❌ Δεν βρέθηκε Company. Ρύθμισε UNITED_TARGET_COMPANY_EMAIL ή δημιούργησε εταιρεία."))
            return

        self.stdout.write(self.style.NOTICE(f"➡️  United sync mode: {'MOCK' if use_mock else 'GRAPH'} → company={company.name}"))

        # 1) Φέρε "μηνύματα"
        if use_mock:
            messages = fetch_mock_messages()
        else:
            messages = fetch_graph_messages(limit=limit)

        created = 0
        skipped = 0

        for m in messages:
            mid = m.get("id") or m.get("internetMessageId") or ""
            if not mid:
                continue

            # idempotency
            if IntegrationInbound.objects.filter(message_id=mid).exists():
                skipped += 1
                continue

            subject = (m.get("subject") or "")[:500]
            body = m.get("body") or ""
            received_dt = m.get("received")
            if isinstance(received_dt, str):
                try:
                    received_dt = timezone.make_aware(timezone.datetime.fromisoformat(received_dt.replace("Z", "+00:00")))
                except Exception:
                    received_dt = None

            parsed = parse_united_email(subject, body)

            # Απαραίτητα πεδία
            if not parsed.get("customer_name") or not parsed.get("start_date") or not parsed.get("end_date"):
                IntegrationInbound.objects.create(
                    message_id=mid, subject=subject, received_at=received_dt, raw_snippet=parsed.get("raw", "")[:1000]
                )
                skipped += 1
                continue

            # Επιλογή οχήματος: προτίμηση στην κατηγορία, αλλιώς πρώτο διαθέσιμο
            car = None
            cat = parsed.get("category")
            if cat:
                car = Car.objects.filter(company=company, category=cat, is_rented=False).order_by("brand", "model").first()
            if not car:
                car = Car.objects.filter(company=company, is_rented=False).order_by("brand", "model").first()
            if not car:
                IntegrationInbound.objects.create(
                    message_id=mid, subject=subject, received_at=received_dt,
                    raw_snippet="NO AVAILABLE CAR | " + (parsed.get("raw", "")[:500])
                )
                skipped += 1
                continue

            with transaction.atomic():
                Booking.objects.create(
                    company=company,
                    car=car,
                    start_date=parsed["start_date"],
                    end_date=parsed["end_date"],
                    customer_name=parsed["customer_name"],
                    customer_phone=parsed.get("customer_phone", ""),
                    extra_insurance=parsed.get("extra_insurance", False),
                    total_price=parsed.get("total_price", 0),
                    status=Booking.STATUS_REQUESTED,
                    created_by=None,
                )
                IntegrationInbound.objects.create(
                    message_id=mid, subject=subject, received_at=received_dt, raw_snippet=parsed.get("raw", "")[:1000]
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(f"✅ Ολοκληρώθηκε. New bookings: {created}, skipped: {skipped}"))

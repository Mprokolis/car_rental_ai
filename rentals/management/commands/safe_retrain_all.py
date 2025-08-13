from django.core.management.base import BaseCommand
from django.core.management import call_command
from recommendations.models import RentalRequest, RentalDecision
from rentals.models import Company
from django.utils import timezone


class Command(BaseCommand):
    help = "Retrains AI model for each company only if new data exists."

    def handle(self, *args, **options):
        retrained = 0

        for company in Company.objects.all():
            last_trained = company.last_trained

            # Βρες rental requests με chosen_car που έγιναν μετά το last_trained (ή όλα αν είναι πρώτη φορά)
            decisions_qs = RentalDecision.objects.filter(
                request__company=company,
                chosen_car__isnull=False,
            )
            if last_trained:
                decisions_qs = decisions_qs.filter(request__created_at__gt=last_trained)

            decision_count = decisions_qs.count()

            if decision_count >= 1:
                self.stdout.write(f"📊 Retraining for: {company.user.username} ({decision_count} new samples)")
                call_command("train_model", company.user.username)

                # ✅ Ενημερώνουμε το last_trained
                company.last_trained = timezone.now()
                company.save(update_fields=["last_trained"])

                retrained += 1
            else:
                self.stdout.write(f"⏭️ Skip: {company.user.username} (no new data)")

        self.stdout.write(f"\n✅ Ολοκληρώθηκε retrain για {retrained} εταιρείες.")

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from rentals.models import Company
from recommendations.models import RentalRequest, RentalDecision

class Command(BaseCommand):
    help = "Καθαρίζει όλα τα training δεδομένα (RentalRequest + RentalDecision) για συγκεκριμένη εταιρεία."

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help="Το username του χρήστη (εταιρείας) που θέλεις να καθαρίσεις.")

    def handle(self, *args, **options):
        username = options['username']

        try:
            user = User.objects.get(username=username)
            company = Company.objects.get(user=user)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ Δεν βρέθηκε χρήστης με username: {username}"))
            return
        except Company.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ Ο χρήστης δεν συνδέεται με κάποια εταιρεία."))
            return

        # Πάρε τα request IDs και σβήσε τα πάντα
        request_ids = RentalRequest.objects.filter(company=company).values_list("id", flat=True)
        num_decisions = RentalDecision.objects.filter(request_id__in=request_ids).delete()
        num_requests = RentalRequest.objects.filter(id__in=request_ids).delete()

        self.stdout.write(self.style.SUCCESS(
            f"✅ Καθαρίστηκαν τα training δεδομένα για την εταιρεία \"{company.name}\" ({username})."
        ))

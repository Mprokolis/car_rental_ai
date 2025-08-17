from django.apps import AppConfig

class RentalsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rentals'

    def ready(self):  # pragma: no cover - called on app init
        # Ξεκινά background thread που φέρνει αυτόματα κρατήσεις από email
        from .email_auto_importer import start_email_importer

        start_email_importer()
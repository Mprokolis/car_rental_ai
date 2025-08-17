import imaplib
import os
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

def env(name, default=None):
    return os.environ.get(name, getattr(settings, name, default))

class Command(BaseCommand):
    help = "Δοκιμή σύνδεσης στο IMAP με τα credentials από .env"

    def handle(self, *args, **options):
        host = env("IMAP_HOST")
        user = env("IMAP_USER")
        pwd  = env("IMAP_PASS")
        folder = env("IMAP_FOLDER", "INBOX")

        if not all([host, user, pwd]):
            raise CommandError("Λείπουν οι IMAP_HOST, IMAP_USER, IMAP_PASS στο .env ή στο settings.")

        self.stdout.write(f"🔌 Σύνδεση στο {host} ως {user}...")
        try:
            mail = imaplib.IMAP4_SSL(host)
            mail.login(user, pwd)
            self.stdout.write(self.style.SUCCESS("✅ Επιτυχής σύνδεση!"))
            mail.select(folder)
            status, data = mail.search(None, "ALL")
            if status == "OK":
                ids = data[0].split()
                self.stdout.write(f"📨 Βρέθηκαν {len(ids)} emails στο φάκελο {folder}.")
            mail.logout()
        except imaplib.IMAP4.error as e:
            raise CommandError(f"Σφάλμα IMAP: {e}")

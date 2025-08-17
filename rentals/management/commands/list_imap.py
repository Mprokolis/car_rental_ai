import imaplib
import os
import re
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

def env(name, default=None):
    return os.environ.get(name, getattr(settings, name, default))

FOLDER_RE = re.compile(r'"([^"]+)"\s*$')  # πιάνει το τελευταίο "Folder" από τη γραμμή του LIST

class Command(BaseCommand):
    help = "Λίστα IMAP φακέλων και πλήθος μηνυμάτων (ALL / UNSEEN). Χρήσιμο για debug."

    def add_arguments(self, parser):
        parser.add_argument("--like", default=None, help="Regex φιλτράρισμα ονόματος φακέλου (π.χ. Gmail).")

    def handle(self, *args, **opts):
        host = env("IMAP_HOST")
        user = env("IMAP_USER")
        pwd  = env("IMAP_PASS")

        if not all([host, user, pwd]):
            raise CommandError("Λείπουν IMAP_HOST, IMAP_USER, IMAP_PASS στο .env ή στο settings.")

        like = opts.get("like")
        regex = re.compile(like) if like else None

        self.stdout.write(f"🔌 Σύνδεση στο {host} ως {user}...")
        m = imaplib.IMAP4_SSL(host)
        m.login(user, pwd)

        typ, boxes = m.list()
        if typ != "OK" or not boxes:
            m.logout()
            raise CommandError("Αποτυχία IMAP LIST.")

        self.stdout.write("📁 Φάκελοι:")
        for raw in boxes:
            line = raw.decode(errors="ignore")
            # Από την απάντηση παίρνουμε το ΤΕΛΕΥΤΑΙΟ quoted κομμάτι ως όνομα φακέλου
            mfolder = None
            m2 = FOLDER_RE.search(line)
            if m2:
                mfolder = m2.group(1)
            else:
                # fallback: πάρε ό,τι υπάρχει μετά το τελευταίο space
                mfolder = line.split()[-1].strip('"')

            if regex and not regex.search(mfolder):
                continue

            # ΠΡΟΣΟΧΗ: χρειάζεται quoting στο SELECT
            typ_sel, _ = m.select(f'"{mfolder}"')
            if typ_sel != "OK":
                self.stdout.write(self.style.WARNING(f"  - {mfolder}: skipped (SELECT failed)"))
                continue

            status_all, data_all = m.search(None, "ALL")
            n_all = len((data_all[0] or b'').split()) if status_all == "OK" else 0

            status_unseen, data_unseen = m.search(None, "UNSEEN")
            n_unseen = len((data_unseen[0] or b'').split()) if status_unseen == "OK" else 0

            self.stdout.write(f"  - {mfolder}: ALL={n_all}, UNSEEN={n_unseen}")

        m.logout()
        self.stdout.write(self.style.SUCCESS("✅ Έγινε."))

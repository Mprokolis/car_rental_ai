import os
import threading
import time

from django.core.management import call_command

_started = False


def _run_loop():
    company = (
        os.environ.get("IMAP_COMPANY")
        or os.environ.get("AUTO_IMPORT_COMPANY")
    )
    if not company:
        return
    interval = int(os.environ.get("EMAIL_IMPORT_INTERVAL", "300"))
    while True:
        try:
            call_command(
                "import_bookings_from_email",
                company=company,
                mark_seen=True,
                auto_convert=True,
            )
        except Exception as exc:  # pragma: no cover - non critical
            print(f"email import error: {exc}")
        time.sleep(interval)


def start_email_importer():
    global _started
    if _started or os.environ.get("DISABLE_EMAIL_AUTO_IMPORT"):
        return
    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    _started = True
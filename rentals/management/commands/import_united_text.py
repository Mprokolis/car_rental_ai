# rentals/management/commands/import_united_text.py
from __future__ import annotations
import sys
import json
from django.core.management.base import BaseCommand, CommandParser
from rentals.parsers import parse_united_rental_text

class Command(BaseCommand):
    help = "Διάβασε United Rent a Car reservation (απλό κείμενο) και τύπωσε τα πεδία σε JSON."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "path",
            nargs="?",
            help="Μονοπάτι σε .txt αρχείο με το κείμενο της κράτησης. Αν λείπει, διαβάζει από stdin.",
        )

    def handle(self, *args, **options):
        path = options.get("path")
        if path:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            # Διάβασε από stdin (μπορείς να κάνεις paste και Ctrl+Z/Enter σε Windows)
            self.stdout.write(self.style.NOTICE("Πάτησε paste το κείμενο και μετά Ctrl+Z + Enter (Windows) ή Ctrl+D (Linux/Mac):"))
            text = sys.stdin.read()

        data = parse_united_rental_text(text)
        # Μετατροπή Decimal -> str για JSON
        def _default(o):
            return str(o)
        self.stdout.write(json.dumps(data, default=_default, ensure_ascii=False, indent=2))

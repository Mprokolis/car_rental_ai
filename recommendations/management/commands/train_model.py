from django.core.management.base import BaseCommand
from recommendations.ml_training import build_training_dataset, train_model, save_model

class Command(BaseCommand):
    help = "Εκπαίδευση του μοντέλου AI για συγκεκριμένη εταιρεία"

    def add_arguments(self, parser):
        parser.add_argument(
            'username',
            type=str,
            help="Το username της εταιρείας για την οποία θα εκπαιδευτεί το AI μοντέλο."
        )

    def handle(self, *args, **options):
        username = options['username']
        self.stdout.write(f"📊 Δημιουργία dataset για: {username}...")

        try:
            df, company = build_training_dataset(username)
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f"❌ {e}"))
            return

        if df.empty:
            self.stdout.write(self.style.WARNING("⚠️  Δεν υπάρχουν αρκετά δεδομένα για training."))
            return

        self.stdout.write("🧠 Εκπαίδευση μοντέλου...")
        model, category_encoder = train_model(df)

        self.stdout.write("💾 Αποθήκευση μοντέλου...")
        save_model(model, category_encoder, company.id)

        self.stdout.write(self.style.SUCCESS(
            f"✅ Το μοντέλο εκπαιδεύτηκε και αποθηκεύτηκε ως model_company_{company.id}.joblib"
        ))

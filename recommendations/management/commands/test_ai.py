from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from sklearn.metrics import accuracy_score
from rentals.models import Company, Car
from recommendations.models import RentalRequest, RentalDecision
import pandas as pd
import joblib
import os


class Command(BaseCommand):
    help = "Υπολογίζει το ποσοστό επιτυχίας του AI μοντέλου για συγκεκριμένη εταιρεία."

    def add_arguments(self, parser):
        parser.add_argument("username", type=str, help="Το username της εταιρείας")

    def handle(self, *args, **options):
        username = options["username"]

        try:
            user = User.objects.get(username=username)
            company = Company.objects.get(user=user)
        except (User.DoesNotExist, Company.DoesNotExist):
            self.stdout.write(self.style.ERROR(f"❌ Δεν βρέθηκε εταιρεία με username '{username}'"))
            return

        model_path = f"model_company_{company.id}.joblib"
        if not os.path.exists(model_path):
            self.stdout.write(self.style.ERROR(f"❌ Δεν βρέθηκε μοντέλο για την εταιρεία '{company.name}'"))
            return

        try:
            model, category_encoder, fuel_encoder = joblib.load(model_path)
        except:
            self.stdout.write(self.style.ERROR("❌ Σφάλμα κατά το φόρτωμα του μοντέλου."))
            return

        decisions = RentalDecision.objects.select_related("request", "chosen_car")\
            .filter(request__company=company, chosen_car__isnull=False)

        y_true, y_pred = [], []
        correct = 0

        self.stdout.write(f"\n📊 Τεστ προβλέψεων για εταιρεία: {company.name} (username: {username})")
        self.stdout.write("------------------------------------------------------")

        for i, decision in enumerate(decisions):
            req = decision.request
            car = decision.chosen_car

            if req.requested_category not in category_encoder.classes_:
                continue

            try:
                cat_encoded = category_encoder.transform([req.requested_category])[0]
                fuel_encoded = fuel_encoder.transform([[car.fuel_type]])[0]
            except:
                continue

            features = [
                req.days,
                float(req.total_price),
                int(req.extra_insurance),
                cat_encoded,
                float(car.price_per_day or 0),
                int(car.extra_insurance),
                *fuel_encoded
            ]

            # ✅ Δημιουργία DataFrame με ονόματα στηλών
            feature_names = [
                "days",
                "total_price",
                "extra_insurance",
                "requested_category_enc",
                "car_price_per_day",
                "car_extra_insurance",
                *fuel_encoder.get_feature_names_out(["car_fuel_type"])
            ]
            input_df = pd.DataFrame([features], columns=feature_names)

            try:
                probas = model.predict_proba(input_df)[0]
                predicted_car_id = model.classes_[probas.argmax()]
            except:
                continue

            is_correct = predicted_car_id == car.id
            y_true.append(car.id)
            y_pred.append(predicted_car_id)
            correct += 1 if is_correct else 0

            predicted_car = Car.objects.filter(id=predicted_car_id).first()
            predicted_str = f"{predicted_car.brand} {predicted_car.model}" if predicted_car else f"ID {predicted_car_id}"

            result = "✅" if is_correct else "❌"
            self.stdout.write(
                f"{result} Request #{decision.id}: Επέλεξε {car.brand} {car.model} | AI πρότεινε {predicted_str}"
            )

        if not y_true:
            self.stdout.write(self.style.WARNING("⚠️ Δεν υπάρχουν επαρκή δεδομένα για αξιολόγηση του μοντέλου."))
            return

        accuracy = accuracy_score(y_true, y_pred)

        self.stdout.write("\n📈 Συνοπτικά:")
        self.stdout.write(self.style.SUCCESS(
            f"🎯 Τελική ακρίβεια: {accuracy:.2%} ({correct} σωστά από {len(y_true)} προβλέψεις)"
        ))

import joblib
from sklearn.metrics import accuracy_score
from django.contrib.auth.models import User
from rentals.models import Company, Car
from recommendations.models import RentalRequest, RentalDecision


def test_model_accuracy(company_username):
    try:
        user = User.objects.get(username=company_username)
        company = Company.objects.get(user=user)
    except (User.DoesNotExist, Company.DoesNotExist):
        print(f"❌ Η εταιρεία με username '{company_username}' δεν βρέθηκε.")
        return

    model_path = f"model_company_{company.id}.joblib"
    try:
        model, category_encoder = joblib.load(model_path)
    except:
        print(f"❌ Δεν βρέθηκε ή δεν φορτώθηκε το μοντέλο για την εταιρεία '{company.name}'.")
        return

    decisions = RentalDecision.objects.select_related("request", "chosen_car")\
        .filter(request__company=company, chosen_car__isnull=False)

    y_true, y_pred = [], []

    for decision in decisions:
        req = decision.request
        car = decision.chosen_car

        if req.requested_category not in category_encoder.classes_:
            continue

        try:
            cat_encoded = category_encoder.transform([req.requested_category])[0]
        except:
            continue

        features = [
            req.days,
            float(req.total_price),
            int(req.extra_insurance),
            cat_encoded,
        ]

        try:
            probas = model.predict_proba([features])[0]
            predicted_car_id = model.classes_[probas.argmax()]
        except:
            continue

        y_true.append(car.id)
        y_pred.append(predicted_car_id)

    if not y_true:
        print("⚠️ Δεν υπάρχουν επαρκή δεδομένα για αξιολόγηση του μοντέλου.")
        return

    accuracy = accuracy_score(y_true, y_pred)
    print(f"✅ Ποσοστό επιτυχίας του AI μοντέλου για '{company.name}': {accuracy:.2%}")

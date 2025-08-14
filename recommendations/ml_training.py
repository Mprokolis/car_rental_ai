import pandas as pd
import joblib
from django.contrib.auth.models import User
from rentals.models import Company
from recommendations.models import RentalRequest, RentalDecision
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder


def build_training_dataset(company_username):
    try:
        user = User.objects.get(username=company_username)
        company = Company.objects.get(user=user)
    except (User.DoesNotExist, Company.DoesNotExist):
        raise ValueError(f"Η εταιρεία με username '{company_username}' δεν βρέθηκε.")

    decisions = RentalDecision.objects.select_related("request", "chosen_car")\
        .filter(request__company=company, chosen_car__isnull=False)

    rows = []
    for decision in decisions:
        req = decision.request
        car = decision.chosen_car
        rows.append({
            "days": req.days,
            "total_price": float(req.total_price),
            "extra_insurance": int(req.extra_insurance),
            "requested_category": req.requested_category,
            "car_id": car.id,
        })

    df = pd.DataFrame(rows)
    print(f"📊 Loaded {len(df)} training samples for company '{company.name}'")

    # Αν θες να περιορίσεις τις εγγραφές για τεστ:
    # df = df[:100]

    return df, company


def train_model(df):
    category_encoder = LabelEncoder()
    df["requested_category_enc"] = category_encoder.fit_transform(
        df["requested_category"]
    )

    X = df[[
        "days",
        "total_price",
        "extra_insurance",
        "requested_category_enc",
    ]]
    y = df["car_id"]

    print("🧠 Training model... (this may take a few seconds)")
    model = RandomForestClassifier(n_estimators=10, random_state=42)  # ⚡ πιο γρήγορο για δοκιμές
    model.fit(X, y)
    print("✅ Training complete.")

    return model, category_encoder


def save_model(model, category_encoder, company_id):
    filename = f"model_company_{company_id}.joblib"
    joblib.dump((model, category_encoder), filename)
    print(f"💾 Model saved to {filename}")

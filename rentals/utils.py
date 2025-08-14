import joblib
import os

MODEL_PATH = "model.joblib"

def rank_cars(request_filters, qs, company_id):
    """AI προτάσεις ανά εταιρεία — με fallback σε default αν δεν υπάρχει μοντέλο."""
    wanted_category = (request_filters.get("category") or "").lower()
    days = int(request_filters.get("days", 1))
    total_price = float(request_filters.get("total_price", 0))
    extra_insurance = 1 if request_filters.get("extra_insurance") else 0

    all_cars = list(qs)
    target_cars = [c for c in all_cars if c.category.lower() == wanted_category]
    other_cars = [c for c in all_cars if c not in target_cars]

    model_path = f"model_company_{company_id}.joblib"
    if not os.path.exists(model_path):
        return default_ranking(request_filters, qs)

    try:
        model, category_encoder = joblib.load(model_path)
    except Exception:
        return default_ranking(request_filters, qs)

    if wanted_category not in category_encoder.classes_:
        return default_ranking(request_filters, qs)

    category_encoded = category_encoder.transform([wanted_category])[0]
    scores = {}
    input_features = [
        days,
        total_price,
        extra_insurance,
        category_encoded,
    ]

    try:
        probas = model.predict_proba([input_features])[0]
        class_ids = model.classes_.tolist()
        for car in target_cars:
            prob = probas[class_ids.index(car.id)] if car.id in class_ids else 0.0
            scores[car] = prob
    except:
        for car in target_cars:
            scores[car] = 0.0

    sorted_target = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    sorted_target = [car for car, _ in sorted_target]
    sorted_others = sorted(other_cars, key=lambda c: (c.brand.lower(), c.model.lower()))
    return sorted_target + sorted_others

def default_ranking(request_filters, qs):
    wanted = (request_filters.get("category") or "").lower()

    def alpha_sort(car):
        return (car.brand.lower(), car.model.lower())

    cars = list(qs)
    if wanted:
        primary = [c for c in cars if c.category.lower() == wanted]
        secondary = [c for c in cars if c.category.lower() != wanted]
        return sorted(primary, key=alpha_sort) + sorted(secondary, key=alpha_sort)
    return sorted(cars, key=alpha_sort)

def default_ranking_direct(car_list):
    def alpha_sort(car):
        return (car.brand.lower(), car.model.lower())
    return sorted(car_list, key=alpha_sort)

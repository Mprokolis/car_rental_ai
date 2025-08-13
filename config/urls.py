# config/urls.py

from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),

    # App routes (με namespace 'rentals')
    path("rentals/", include(("rentals.urls", "rentals"), namespace="rentals")),

    # --- Convenience redirects ---
    # Αρχική σελίδα → επιλογή αυτοκινήτου
    path("", RedirectView.as_view(pattern_name="rentals:select_car", permanent=False)),
    # Συμβατικά short paths για login/logout/select-car ώστε να δουλεύουν
    path("login/", RedirectView.as_view(pattern_name="rentals:login_company", permanent=False)),
    path("logout/", RedirectView.as_view(pattern_name="rentals:logout_company", permanent=False)),
    path("select-car/", RedirectView.as_view(pattern_name="rentals:select_car", permanent=False)),
]

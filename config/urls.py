# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),

    # App routes (με namespace 'rentals')
    path("rentals/", include(("rentals.urls", "rentals"), namespace="rentals")),

    # --- Convenience redirects ---
    # Αρχική σελίδα → επιλογή αυτοκινήτου
    path("", RedirectView.as_view(pattern_name="rentals:select_car", permanent=False)),
    # Συμβατικά short paths για login/logout/select-car
    path("login/", RedirectView.as_view(pattern_name="rentals:login_company", permanent=False)),
    path("logout/", RedirectView.as_view(pattern_name="rentals:logout_company", permanent=False)),
    path("select-car/", RedirectView.as_view(pattern_name="rentals:select_car", permanent=False)),
]

# Media (PDFs) μόνο σε development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

from django.contrib import admin
from .models import RentalRequest, RentalDecision

admin.site.register(RentalRequest)
admin.site.register(RentalDecision)

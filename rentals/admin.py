from django.contrib import admin
from .models import Car, Company

@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    # Κρύβουμε τα οικονομικά πεδία όπως πριν
    exclude = ('price_per_day', 'extra_insurance')

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    pass

from django.db import models
from rentals.models import Company, Car

class RentalRequest(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    days = models.PositiveSmallIntegerField()
    total_price = models.DecimalField(max_digits=8, decimal_places=2)
    extra_insurance = models.BooleanField(default=False)
    requested_category = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Request: {self.requested_category} | {self.total_price}€"


class RentalDecision(models.Model):
    request = models.OneToOneField(RentalRequest, on_delete=models.CASCADE)
    chosen_car = models.ForeignKey(Car, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Decision for Request #{self.request.id}"

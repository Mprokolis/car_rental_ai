from django.db import models
from django.contrib.auth.models import User

class Company(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    last_trained = models.DateTimeField(null=True, blank=True)  # retrain bookkeeping

    def __str__(self):
        return self.name


class Car(models.Model):
    """
    Στόλος οχημάτων.
    • `is_rented` δηλώνει αν το όχημα είναι δεσμευμένο.
    • Κατηγορίες: small / medium / compact.
    """
    CATEGORY_CHOICES = [
        ("small", "Small"),
        ("medium", "Medium"),
        ("compact", "Compact"),
    ]
    FUEL_CHOICES = [
        ("petrol", "Βενζίνη"),
        ("diesel", "Πετρέλαιο"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    brand = models.CharField(max_length=50)
    model = models.CharField(max_length=50)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    fuel_type = models.CharField(max_length=20, choices=FUEL_CHOICES, default="petrol")

    # προαιρετικά οικονομικά (δεν τα εμφανίζεις στη λίστα επιλογής)
    price_per_day = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    extra_insurance = models.BooleanField(default=False)

    # Αριθμός Κυκλοφορίας — μοναδικός ανά εταιρεία
    license_plate = models.CharField("Αριθμός Κυκλοφορίας", max_length=20, null=True, blank=True)

    # κατάσταση διαθεσιμότητας
    is_rented = models.BooleanField(default=False)
    available = models.BooleanField(default=True)  # για backward-compat

    def __str__(self):
        return f"{self.brand} {self.model}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "license_plate"],
                name="uniq_plate_per_company",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "is_rented"]),
            models.Index(fields=["category"]),
            models.Index(fields=["fuel_type"]),
        ]

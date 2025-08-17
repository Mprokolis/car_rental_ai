from django.db import models
from django.contrib.auth.models import User
from datetime import timedelta

class Company(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    last_trained = models.DateTimeField(null=True, blank=True)  # retrain bookkeeping

    def __str__(self):
        return self.name


class Car(models.Model):
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

    # προαιρετικά οικονομικά (δεν φαίνονται στις λίστες επιλογής)
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


class Booking(models.Model):
    """
    Εισερχόμενες κρατήσεις που έρχονται με email (PDF).
    Status: imported / active / completed / cancelled.
    """
    STATUS_CHOICES = [
        ("imported", "Imported"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="bookings")

    # βασικά στοιχεία πελάτη/κράτησης
    customer_name = models.CharField(max_length=120, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=50, blank=True)
    booking_code = models.CharField(max_length=20, blank=True)

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    requested_category = models.CharField(max_length=20, blank=True)  # small/medium/compact
    extra_insurance = models.BooleanField(default=False)

    # meta
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="imported")
    source_email_uid = models.CharField(max_length=120, blank=True)   # IMAP UID (ανά φάκελο)
    gm_msgid = models.CharField(max_length=120, blank=True)           # X-GM-MSGID (global, ιδανικό για dedupe)
    raw_pdf_path = models.CharField(max_length=500, blank=True)       # path αποθήκευσης PDF
    created_at = models.DateTimeField(auto_now_add=True)

    # optional: link σε επιλεγμένο όχημα αργότερα
    chosen_car = models.ForeignKey('Car', null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"Booking #{self.id} ({self.status})"

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.booking_code:
            self.booking_code = f"G5{self.id}"
            super().save(update_fields=["booking_code"])

    @property
    def days(self) -> int:
        if self.start_date and self.end_date:
            d = (self.end_date - self.start_date).days
            return d if d > 0 else 1
        return 1

    def to_rental_request(self):
        """
        Δημιουργεί RentalRequest & κενό RentalDecision από την κράτηση.
        Επιστρέφει (rental_request, rental_decision).
        """
        from recommendations.models import RentalRequest, RentalDecision  # τοπικό import για να μην κάνουμε κυκλικό
        rr = RentalRequest.objects.create(
            company=self.company,
            days=self.days,
            total_price=self.total_price or 0,
            extra_insurance=bool(self.extra_insurance),
            requested_category=(self.requested_category or ""),
        )
        dec = RentalDecision.objects.create(request=rr)
        return rr, dec

    class Meta:
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["created_at"]),
        ]

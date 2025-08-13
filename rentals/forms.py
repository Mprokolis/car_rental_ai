from datetime import date
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User

from .models import Car, Company

# ΔΕΧΟΜΑΣΤΕ DD-MM-YYYY (και ISO για ασφάλεια)
DATE_INPUT_FORMATS = ["%d-%m-%Y", "%Y-%m-%d"]

# ---------------------------------------------------------------------------
# Εγγραφή Εταιρείας
# ---------------------------------------------------------------------------

class CompanyRegistrationForm(forms.ModelForm):
    username = forms.CharField(
        label="Όνομα Χρήστη", max_length=150, help_text="Αυτό θα χρησιμοποιείται για login."
    )
    password = forms.CharField(
        label="Κωδικός", widget=forms.PasswordInput, help_text="Εισάγετε έναν ασφαλή κωδικό."
    )

    class Meta:
        model = Company
        fields = ["name", "email", "username", "password"]

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Αυτό το όνομα χρήστη υπάρχει ήδη.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Αυτό το email χρησιμοποιείται ήδη.")
        return email


# ---------------------------------------------------------------------------
# Login Εταιρείας
# ---------------------------------------------------------------------------

class CompanyLoginForm(AuthenticationForm):
    username = forms.CharField(label="Όνομα Χρήστη", max_length=150)
    password = forms.CharField(label="Κωδικός", widget=forms.PasswordInput)


# ---------------------------------------------------------------------------
# Επιλογή Αυτοκινήτου
# ---------------------------------------------------------------------------

CAR_CATEGORIES = [
    ("small", "Small"),
    ("medium", "Medium"),
    ("compact", "Compact"),
]

class CarSelectionForm(forms.Form):
    start_date = forms.DateField(
        label="Ημερομηνία Έναρξης",
        input_formats=DATE_INPUT_FORMATS,
        widget=forms.DateInput(
            attrs={"type": "text", "class": "datepicker", "placeholder": "DD-MM-YYYY"}
        ),
        required=False,
    )
    end_date = forms.DateField(
        label="Ημερομηνία Λήξης",
        input_formats=DATE_INPUT_FORMATS,
        widget=forms.DateInput(
            attrs={"type": "text", "class": "datepicker", "placeholder": "DD-MM-YYYY"}
        ),
        required=False,
    )
    total_price = forms.DecimalField(label="Συνολικό Ποσό Πληρωμής (€)", required=False)
    category = forms.ChoiceField(
        label="Κατηγορία Αυτοκινήτου", choices=CAR_CATEGORIES, required=False
    )
    extra_insurance = forms.BooleanField(label="Έξτρα Ασφάλεια;", required=False)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            raise forms.ValidationError("Η ημερομηνία λήξης πρέπει να είναι μετά την έναρξη.")
        if start and end:
            cleaned["days"] = (end - start).days or 1
        return cleaned


# ---------------------------------------------------------------------------
# Προσθήκη/Επεξεργασία Αυτοκινήτου
# ---------------------------------------------------------------------------

class CarForm(forms.ModelForm):
    class Meta:
        model = Car
        fields = ["brand", "model", "category", "fuel_type", "license_plate"]
        widgets = {
            "category": forms.Select(choices=CAR_CATEGORIES),
        }
        labels = {
            "brand": "Μάρκα",
            "model": "Μοντέλο",
            "category": "Κατηγορία",
            "fuel_type": "Καύσιμο",
            "license_plate": "Αριθμός Κυκλοφορίας",
        }

    def clean_license_plate(self):
        lp = self.cleaned_data["license_plate"]
        if lp is None:
            return lp
        return lp.strip().upper()

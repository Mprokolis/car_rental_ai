from urllib.parse import urlparse
from datetime import date

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Company, Booking
from .utils_email import parse_booking_text


class PasswordResetFlowTests(TestCase):
    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_password_reset_flow(self):
        user = User.objects.create_user(
            username='alice', email='alice@example.com', password='oldpass123'
        )

        response = self.client.post(
            reverse('rentals:password_reset'), {'email': 'alice@example.com'}
        )
        self.assertRedirects(response, reverse('rentals:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)

        reset_link = next(
            line for line in mail.outbox[0].body.splitlines() if '/reset/' in line
        )
        path = urlparse(reset_link).path

        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        set_path = response.url

        response = self.client.get(set_path)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            set_path,
            {
                'new_password1': 'newpass456',
                'new_password2': 'newpass456',
            },
        )
        self.assertRedirects(response, reverse('rentals:password_reset_complete'))

        user.refresh_from_db()
        self.assertTrue(user.check_password('newpass456'))


class BookingViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='bob', email='bob@example.com', password='pass123'
        )
        self.company = Company.objects.create(
            user=self.user, name='Bob Co', email='bob@example.com'
        )
        self.booking = Booking.objects.create(
            company=self.company,
            customer_name='John',
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
        )

    def test_bookings_list_loads(self):
        self.client.login(username='bob', password='pass123')
        resp = self.client.get(reverse('rentals:bookings_list'))
        self.assertContains(resp, self.booking.booking_code)

    def test_booking_set_status(self):
        self.client.login(username='bob', password='pass123')
        url = reverse('rentals:booking_set_status', args=[self.booking.id, 'activate'])
        resp = self.client.post(url)
        self.assertRedirects(resp, reverse('rentals:bookings_list'))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'active')


class EmailParsingTests(TestCase):
    def test_parse_booking_text_from_body(self):
        sample = (
            "Name: Luciano Pasquali\n"
            "Phone Number: 2101234567\n"
            "Vehicle Class: ECMD\n"
            "Pick up Location: Heraklion\nDate: 18/08/2025 14:00\n"
            "Return Location: Heraklion\nDate: 29/08/2025 10:30\n"
        )
        data = parse_booking_text(sample)
        self.assertEqual(data["customer_name"], "Luciano Pasquali")
        self.assertEqual(data["customer_phone"], "2101234567")
        self.assertEqual(data["requested_category"], "ecmd")
        self.assertEqual(str(data["start_date"]), "2025-08-18")
        self.assertEqual(str(data["end_date"]), "2025-08-29")

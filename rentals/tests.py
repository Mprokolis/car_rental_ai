from urllib.parse import urlparse

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


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

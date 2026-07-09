from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.inbox.models import Inbox


class ConsoleAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")
        self.customer = User.objects.create_user("cust", "cust@x.com", "pass", role="customer")

    def test_admin_can_open_settings(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("console:settings_home")).status_code, 200)

    def test_customer_redirected_from_settings(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("console:settings_home"))
        self.assertEqual(resp.status_code, 302)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("console:inbox_list"))
        self.assertEqual(resp.status_code, 302)


class InboxFormTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")
        self.client.force_login(self.admin)

    def test_create_inbox(self):
        resp = self.client.post(
            reverse("console:inbox_create"),
            {
                "name": "Support",
                "email_address": "s@x.com",
                "smtp_port": 587,
                "imap_port": 993,
                "imap_folder": "INBOX",
                "is_default": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Inbox.objects.filter(email_address="s@x.com", is_default=True).exists())

    def test_setting_default_clears_previous_default(self):
        first = Inbox.objects.create(name="A", email_address="a@x.com", is_default=True)
        self.client.post(
            reverse("console:inbox_create"),
            {
                "name": "B",
                "email_address": "b@x.com",
                "smtp_port": 587,
                "imap_port": 993,
                "imap_folder": "INBOX",
                "is_default": "on",
            },
        )
        first.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(Inbox.objects.get(email_address="b@x.com").is_default)

    def test_blank_password_keeps_stored_value(self):
        inbox = Inbox.objects.create(
            name="A", email_address="a@x.com", smtp_host="mail.x.com", smtp_password="secret"
        )
        self.client.post(
            reverse("console:inbox_edit", args=[inbox.pk]),
            {
                "name": "A",
                "email_address": "a@x.com",
                "smtp_host": "mail.x.com",
                "smtp_port": 587,
                "smtp_password": "",  # left blank
                "imap_port": 993,
                "imap_folder": "INBOX",
            },
        )
        inbox.refresh_from_db()
        self.assertEqual(inbox.smtp_password, "secret")

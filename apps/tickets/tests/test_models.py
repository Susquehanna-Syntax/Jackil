from django.test import TestCase

from apps.accounts.models import User
from apps.tickets.models import Attachment, Ticket, TicketMessage


class TicketMessageDefaultsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass", role="customer")
        self.ticket = Ticket.objects.create(title="T", description="D", created_by=self.user)

    def test_message_defaults(self):
        msg = TicketMessage.objects.create(ticket=self.ticket, body="hello")
        self.assertEqual(msg.kind, "reply")
        self.assertTrue(msg.is_public)
        self.assertFalse(msg.is_email)


class TicketMessageAuthorDisplayTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass", role="customer")
        self.ticket = Ticket.objects.create(title="T", description="D", created_by=self.user)

    def test_message_author_display_falls_back(self):
        msg = TicketMessage.objects.create(ticket=self.ticket, from_email="a@b.com")
        self.assertEqual(msg.author_display, "a@b.com")

        msg2 = TicketMessage.objects.create(ticket=self.ticket)
        self.assertEqual(msg2.author_display, "System")


class AttachmentSizeDisplayTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass", role="customer")
        self.ticket = Ticket.objects.create(title="T", description="D", created_by=self.user)

    def test_attachment_size_display(self):
        a1 = Attachment(ticket=self.ticket, original_name="f.txt", size=2048)
        self.assertEqual(a1.size_display, "2.0 KB")

        a2 = Attachment(ticket=self.ticket, original_name="f.txt", size=512)
        self.assertEqual(a2.size_display, "512 B")

from django.core import mail
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.inbox.email_service import send_ticket_reply
from apps.inbox.models import Inbox
from apps.tickets.models import Ticket, TicketMessage


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InboxTests(TestCase):
    def test_reply_to_address(self):
        inbox = Inbox(email_address="support@acme.com", name="Support")
        self.assertEqual(inbox.reply_to_address(42), "support+42@acme.com")

    def test_get_default_prefers_is_default(self):
        Inbox.objects.create(
            name="Default", email_address="default@acme.com", is_default=True, active=True
        )
        Inbox.objects.create(
            name="Other", email_address="other@acme.com", is_default=False, active=True
        )
        default = Inbox.get_default()
        self.assertEqual(default.email_address, "default@acme.com")

    def test_send_ticket_reply_sends_email(self):
        user = User.objects.create_user(
            username="tester",
            email="tester@example.com",
            password="test",
        )
        Inbox.objects.create(
            name="Support",
            email_address="support@acme.com",
            is_default=True,
            active=True,
        )
        ticket = Ticket.objects.create(
            title="Test ticket",
            description="Test description",
            created_by=user,
        )

        msg = TicketMessage.objects.create(
            ticket=ticket,
            author=user,
            kind="reply",
            body="Your issue is resolved.",
            is_public=True,
        )
        result = send_ticket_reply(msg)
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f"[#{ticket.id}]", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [user.email])
        msg.refresh_from_db()
        self.assertEqual(msg.email_status, "sent")

    def test_send_ticket_reply_skips_without_recipient(self):
        Inbox.objects.create(
            name="Support",
            email_address="support@acme.com",
            is_default=True,
            active=True,
        )
        user_no_email = User.objects.create_user(username="noemail", email="", password="test")
        ticket = Ticket.objects.create(
            title="No email ticket",
            description="Test",
            created_by=user_no_email,
            requester_email="",
        )
        msg = TicketMessage.objects.create(
            ticket=ticket,
            author=user_no_email,
            kind="reply",
            body="Hello",
            is_public=True,
        )
        result = send_ticket_reply(msg)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_reply_threads_onto_inbound(self):
        user = User.objects.create_user(
            username="threader",
            email="threader@example.com",
            password="test",
        )
        Inbox.objects.create(
            name="Support",
            email_address="support@acme.com",
            is_default=True,
            active=True,
        )
        ticket = Ticket.objects.create(
            title="Threaded ticket",
            description="Test",
            created_by=user,
        )
        inbound = TicketMessage.objects.create(
            ticket=ticket,
            kind="incoming_email",
            body="Customer inquiry",
            message_id="<inbound-123@example.com>",
            is_public=True,
        )
        reply_msg = TicketMessage.objects.create(
            ticket=ticket,
            author=user,
            kind="reply",
            body="We are looking into this.",
            is_public=True,
        )
        send_ticket_reply(reply_msg)
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn("In-Reply-To", sent_email.extra_headers)
        self.assertEqual(sent_email.extra_headers["In-Reply-To"], inbound.message_id)

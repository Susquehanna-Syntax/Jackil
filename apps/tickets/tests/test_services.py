from django.test import TestCase

from apps.accounts.models import User
from apps.tickets.models import Ticket
from apps.tickets.services import post_message, record_system_event


class PostMessageTest(TestCase):
    def setUp(self):
        self.agent = User.objects.create_user(username="agent", password="pass", role="agent")
        self.ticket = Ticket.objects.create(title="T", description="D", created_by=self.agent)

    def test_reply_is_public_note_is_private(self):
        reply = post_message(self.ticket, self.agent, "hi", kind="reply")
        note = post_message(self.ticket, self.agent, "secret", kind="note")
        self.assertTrue(reply.is_public)
        self.assertFalse(note.is_public)

    def test_explicit_is_public_overrides_default(self):
        msg = post_message(self.ticket, self.agent, "x", kind="note", is_public=True)
        self.assertTrue(msg.is_public)

    def test_system_event_is_internal(self):
        ev = record_system_event(self.ticket, self.agent, "Status changed.")
        self.assertEqual(ev.kind, "system")
        self.assertFalse(ev.is_public)

from django.test import TestCase

from apps.accounts.models import User
from apps.tickets.models import Ticket, TicketMessage
from apps.tickets.permissions import (
    can_post_internal,
    can_view_ticket,
    visible_messages,
)


class VisibleMessagesTest(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username="cust", password="pass", role="customer")
        self.agent = User.objects.create_user(username="agent", password="pass", role="agent")
        self.ticket = Ticket.objects.create(title="T", description="D", created_by=self.customer)
        TicketMessage.objects.create(
            ticket=self.ticket, kind="reply", is_public=True, body="public"
        )
        TicketMessage.objects.create(ticket=self.ticket, kind="note", is_public=False, body="note")

    def test_visible_messages_hides_notes_from_customer(self):
        customer_msgs = visible_messages(self.customer, self.ticket)
        self.assertEqual(customer_msgs.count(), 1)
        self.assertTrue(customer_msgs.first().is_public)

        agent_msgs = visible_messages(self.agent, self.ticket)
        self.assertEqual(agent_msgs.count(), 2)


class CanViewTicketTest(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            username="creator", password="pass", role="customer"
        )
        self.other_customer = User.objects.create_user(
            username="other", password="pass", role="customer"
        )
        self.agent = User.objects.create_user(username="agent", password="pass", role="agent")
        self.admin = User.objects.create_user(username="admin", password="pass", role="admin")
        self.ticket = Ticket.objects.create(title="T", description="D", created_by=self.creator)

    def test_can_view_ticket(self):
        self.assertTrue(can_view_ticket(self.creator, self.ticket))
        self.assertFalse(can_view_ticket(self.other_customer, self.ticket))
        self.assertTrue(can_view_ticket(self.agent, self.ticket))
        self.assertTrue(can_view_ticket(self.admin, self.ticket))


class CanPostInternalTest(TestCase):
    def setUp(self):
        self.agent = User.objects.create_user(username="agent", password="pass", role="agent")
        self.admin = User.objects.create_user(username="admin", password="pass", role="admin")
        self.customer = User.objects.create_user(username="cust", password="pass", role="customer")

    def test_can_post_internal(self):
        self.assertTrue(can_post_internal(self.agent))
        self.assertTrue(can_post_internal(self.admin))
        self.assertFalse(can_post_internal(self.customer))

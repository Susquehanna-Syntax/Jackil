"""The All Tickets list filters as you type; customers keep their own page."""

from django.test import TestCase

from apps.accounts.models import User
from apps.tickets.models import Ticket


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class TicketsLiveFilterTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.customer = make_user("boa", "customer")
        self.open = Ticket.objects.create(
            title="Fibre is down", description="", created_by=self.agent, status="open"
        )
        self.closed = Ticket.objects.create(
            title="Old VPN request", description="", created_by=self.agent, status="closed"
        )

    def test_ticket_partial_filters_by_status(self):
        self.client.force_login(self.agent)
        response = self.client.get("/tickets/?status=closed&partial=1")
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Old VPN request", body)
        self.assertNotIn("Fibre is down", body)
        self.assertNotIn("<html", body)

    def test_ticket_list_has_named_selects_and_no_inline_apply_script(self):
        self.client.force_login(self.agent)
        body = self.client.get("/tickets/").content.decode()
        for needle in ('name="status"', 'name="priority"', 'name="assigned"'):
            self.assertIn(needle, body)
        self.assertIn("data-live-query", body)
        self.assertNotIn("applyFilters", body)

    def test_customer_still_gets_their_own_list(self):
        self.client.force_login(self.customer)
        Ticket.objects.create(title="Printer on my floor", description="", created_by=self.customer)
        response = self.client.get("/tickets/")
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "tickets/customer_tickets.html")
        self.assertIn("My Tickets", body)
        self.assertIn("Printer on my floor", body)

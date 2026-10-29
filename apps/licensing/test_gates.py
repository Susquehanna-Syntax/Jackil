"""The SQSY Business gates: what a free Jackil refuses to offer."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.tickets.models import Ticket, TicketRating
from config import context_processors


def business_on():
    """Patch the one function ``feature_enabled`` asks for a Business slug."""
    patcher = patch("apps.licensing.service.has_feature", side_effect=lambda slug: True)
    patcher.start()
    return patcher


class BusinessGateTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user("cara", password="pw", role="customer")
        self.agent = User.objects.create_user("adam", password="pw", role="agent")
        self.admin = User.objects.create_user("amara", password="pw", role="admin")
        self.ticket = Ticket.objects.create(title="Printer is on fire", created_by=self.customer)
        self.addCleanup(patch.stopall)

    def login(self, user):
        self.client.force_login(user)

    def test_export_is_business_only_and_says_so(self):
        self.login(self.agent)

        off = self.client.get(reverse("tickets:ticket_export"))
        self.assertEqual(off.status_code, 402)
        self.assertContains(off, "part of SQSY Business", status_code=402)
        self.assertIn(
            "CSV export is part of SQSY Business.",
            off.content.decode(),
            "the sentence must name the feature that is missing",
        )

        listing = self.client.get(reverse("tickets:ticket_list"))
        self.assertEqual(listing.status_code, 200)
        self.assertNotContains(listing, "Export CSV")

        business_on()
        on = self.client.get(reverse("tickets:ticket_export"))
        self.assertEqual(on.status_code, 200)
        self.assertEqual(on["Content-Type"], "text/csv")
        self.assertIn(b"Printer is on fire", on.content)

        listing = self.client.get(reverse("tickets:ticket_list"))
        self.assertContains(listing, "Export CSV")

    def test_activity_log_is_business_only(self):
        self.login(self.agent)

        off = self.client.get(reverse("tickets:activity_log"))
        self.assertEqual(off.status_code, 402)
        self.assertContains(off, "part of SQSY Business", status_code=402)

        listing = self.client.get(reverse("tickets:ticket_list"))
        self.assertNotContains(listing, "Activity")

        business_on()
        on = self.client.get(reverse("tickets:activity_log"))
        self.assertEqual(on.status_code, 200)

        listing = self.client.get(reverse("tickets:ticket_list"))
        self.assertContains(listing, "Activity")

    def test_rating_is_not_collected_without_business_but_old_ratings_show(self):
        resolved = Ticket.objects.create(
            title="Fixed last week", created_by=self.customer, status="resolved"
        )
        self.login(self.customer)

        detail = self.client.get(reverse("tickets:ticket_detail", args=[resolved.pk]))
        self.assertNotContains(detail, "How was your support experience?")

        post = self.client.post(
            reverse("tickets:ticket_rate", args=[resolved.pk]), {"score": "5", "comment": "ok"}
        )
        self.assertEqual(post.status_code, 302)
        self.assertEqual(post["Location"], reverse("tickets:ticket_detail", args=[resolved.pk]))
        self.assertFalse(TicketRating.objects.filter(ticket=resolved).exists())
        self.assertContains(
            self.client.get(reverse("tickets:ticket_detail", args=[resolved.pk]), follow=True),
            "Ratings are not being collected.",
        )

        old = TicketRating.objects.create(ticket=self.ticket, score=4, created_by=self.customer)
        aged = self.client.get(reverse("tickets:ticket_detail", args=[self.ticket.pk]))
        self.assertContains(aged, "You rated this 4/5")
        self.assertEqual(old.score, 4)

    def test_context_has_business_features(self):
        request = SimpleNamespace(user=self.customer)

        self.assertEqual(context_processors.business(request), {"business_features": set()})

        business_on()
        self.assertEqual(
            context_processors.business(request)["business_features"],
            {
                "portal_branding",
                "saml",
                "csv_export",
                "audit_log",
                "csat",
                "white_label",
            },
        )

    def test_business_page_links_admins_to_the_edition_page(self):
        self.login(self.admin)

        page = self.client.get(reverse("tickets:ticket_export"))
        self.assertContains(page, reverse("console:edition_settings"), status_code=402)

        self.login(self.agent)
        no_link = self.client.get(reverse("tickets:ticket_export"))
        self.assertNotContains(no_link, reverse("console:edition_settings"), status_code=402)

"""The customer help center reads published wiki pages, and only those."""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.tickets.models import Ticket
from apps.wiki.models import Page, Space


class HelpCenterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("help-agent", "ha@x.com", "pw", role="agent")
        cls.customer = User.objects.create_user("help-cust", "hc@x.com", "pw", role="customer")
        cls.other = User.objects.create_user("help-other", "ho@x.com", "pw", role="customer")
        space = Space.objects.create(name="Help tests")
        cls.public = Page.objects.create(
            space=space,
            title="Printer setup guide",
            body="Install the driver.",
            is_published_to_help_center=True,
        )
        cls.internal = Page.objects.create(
            space=space, title="Printer admin password", body="secret runbook"
        )

    def test_customer_sees_published_pages_only(self):
        self.client.force_login(self.customer)
        body = self.client.get(reverse("help:home")).content.decode()
        self.assertIn("Printer setup guide", body)
        self.assertNotIn("Printer admin password", body)
        search = self.client.get(reverse("help:home"), {"q": "Printer"}).content.decode()
        self.assertIn("Printer setup guide", search)
        self.assertNotIn("Printer admin password", search)

    def test_unpublished_page_is_404_at_the_help_url_even_for_staff(self):
        for user in (self.customer, self.agent):
            self.client.force_login(user)
            url = reverse("help:article", args=[self.internal.slug])
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_published_article_renders_for_a_customer(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("help:article", args=[self.public.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Install the driver.")

    def test_legacy_url_redirects_301_to_the_article(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("help:legacy", args=[self.public.slug]))
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], reverse("help:article", args=[self.public.slug]))

    def test_legacy_url_for_an_internal_page_redirects_staff_and_404s_customers(self):
        url = reverse("help:legacy", args=[self.internal.slug])
        self.client.force_login(self.agent)
        resp = self.client.get(url)
        self.assertIn(resp.status_code, (301, 302))
        self.assertEqual(resp["Location"], reverse("wiki:page_detail", args=[self.internal.slug]))
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_customer_render_has_no_dynamic_link_chips(self):
        ticket = Ticket.objects.create(title="Someone else's ticket", created_by=self.other)
        self.public.body = f"See [[ticket:{ticket.pk}]]."
        self.public.save()
        self.client.force_login(self.customer)
        body = self.client.get(reverse("help:article", args=[self.public.slug])).content.decode()
        self.assertNotIn(reverse("tickets:ticket_detail", args=[ticket.pk]), body)
        self.assertNotIn("Someone else", body)

    def test_staff_search_marks_internal_pages_and_links_them_to_the_wiki(self):
        self.client.force_login(self.agent)
        body = self.client.get(reverse("help:home"), {"q": "Printer"}).content.decode()
        self.assertIn(reverse("wiki:page_detail", args=[self.internal.slug]), body)
        self.assertIn("Internal", body)

    def test_console_has_no_knowledge_base_section_and_links_the_wiki(self):
        admin = User.objects.create_user("help-admin", "hd@x.com", "pw", role="admin")
        self.client.force_login(admin)
        body = self.client.get(reverse("console:settings_home")).content.decode()
        self.assertNotIn("Knowledge Base", body)
        self.assertIn(reverse("wiki:home"), body)

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get(reverse("help:home"))
        self.assertEqual(resp.status_code, 302)

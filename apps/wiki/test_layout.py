"""The wiki's shape (M13): trees, reading order, needs attention, the home
search, page owners, and the all-pages view."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.links.models import DynamicLink
from apps.tickets.models import Ticket
from apps.wiki.models import Page, Space
from apps.wiki.service import needs_attention, neighbours, page_tree, reading_order


class TreeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.space = Space.objects.create(name="Servers")
        cls.runbooks = Page.objects.create(space=cls.space, title="Runbooks", order=1)
        cls.mail = Page.objects.create(
            space=cls.space, title="Mail relay", parent=cls.runbooks, order=1
        )
        cls.printer = Page.objects.create(
            space=cls.space, title="Print server", parent=cls.runbooks, order=2
        )
        cls.spooler = Page.objects.create(
            space=cls.space, title="Spooler stuck", parent=cls.printer
        )
        cls.machines = Page.objects.create(space=cls.space, title="Machines", order=2)

    def test_tree_nests_in_editor_order(self):
        nodes = page_tree(self.space)
        self.assertEqual([n.page for n in nodes], [self.runbooks, self.machines])
        self.assertEqual([n.page for n in nodes[0].children], [self.mail, self.printer])
        self.assertEqual(nodes[0].children[1].children[0].page, self.spooler)
        self.assertEqual(nodes[0].children[1].children[0].depth, 2)

    def test_reading_order_is_depth_first(self):
        self.assertEqual(
            reading_order(page_tree(self.space)),
            [self.runbooks, self.mail, self.printer, self.spooler, self.machines],
        )

    def test_neighbours_follow_reading_order(self):
        self.assertEqual(neighbours(self.printer), (self.mail, self.spooler))
        self.assertEqual(neighbours(self.runbooks), (None, self.mail))
        self.assertEqual(neighbours(self.machines), (self.spooler, None))


class NeedsAttentionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("aria", password="x", role="agent")
        cls.space = Space.objects.create(name="Ops")

    def page(self, title, **fields):
        return Page.objects.create(space=self.space, title=title, owner=self.agent, **fields)

    def test_open_ticket_links_come_first_then_stale_then_unowned(self):
        linked = self.page("Print server")
        stale = self.page("Old NAS")
        Page.objects.filter(pk=stale.pk).update(updated_at=timezone.now() - timedelta(days=200))
        unowned = Page.objects.create(space=self.space, title="Getting started")
        fresh = self.page("Fresh and owned")
        open_ticket = Ticket.objects.create(
            title="Printer down", description="x", created_by=self.agent
        )
        closed = Ticket.objects.create(
            title="Old", description="x", created_by=self.agent, status="closed"
        )
        DynamicLink.objects.create(
            source_type="ticket",
            source_id=str(open_ticket.pk),
            target_type="page",
            target_id=str(linked.pk),
        )
        DynamicLink.objects.create(
            source_type="page",
            source_id=str(fresh.pk),
            target_type="ticket",
            target_id=str(closed.pk),
        )

        found = [(p, r) for p, r in needs_attention(limit=50) if p.space_id == self.space.pk]
        self.assertEqual([p for p, _ in found], [linked, stale, unowned])
        self.assertEqual(found[0][1], "linked to 1 open ticket")
        self.assertTrue(found[1][1].startswith("not edited in 6 month"))
        self.assertEqual(found[2][1], "no owner")


class HomeAndPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("aria", password="x", role="agent")
        cls.customer = User.objects.create_user("cust", password="x", role="customer")
        cls.space = Space.objects.create(name="Servers", description="Runbooks for every machine.")
        cls.bare = Space.objects.create(name="Bare")
        for n in range(5):
            Page.objects.create(
                space=cls.space, title=f"Page {n}", body=f"# Page {n}\n\nBody about spooler {n}."
            )

    def test_home_cards_show_three_pages_and_the_count(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("wiki:home"))
        self.assertContains(response, "All 5 pages")
        self.assertContains(response, "Runbooks for every machine.")
        self.assertNotContains(response, "No description")
        self.assertContains(response, 'href="/wiki/tree/"')

    def test_home_search_returns_matches_as_a_fragment(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("wiki:home"), {"q": "spooler 3", "partial": "1"})
        self.assertContains(response, "data-live-results")
        self.assertContains(response, "Page 3")
        self.assertNotContains(response, "Page 1<")
        self.assertNotContains(response, "<html")

    def test_all_pages_lists_every_space(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("wiki:tree"))
        self.assertContains(response, "Servers")
        self.assertContains(response, "Bare")
        self.assertContains(response, "data-wt-filter")

    def test_customers_cannot_open_the_wiki_home_or_tree(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("wiki:home")).status_code, 403)
        self.assertEqual(self.client.get(reverse("wiki:tree")).status_code, 403)

    def test_page_shows_owner_previous_next_and_read_time(self):
        first, second = Page.objects.filter(space=self.space).order_by("order", "title", "pk")[:2]
        first.owner = self.agent
        first.save()
        self.client.force_login(self.agent)
        response = self.client.get(first.get_absolute_url())
        self.assertContains(response, "Owner: aria")
        self.assertContains(response, "1 min read")
        self.assertContains(response, f'href="{second.get_absolute_url()}" class="wk-pn-next"')


class OwnerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("aria", password="x", role="agent")
        cls.customer = User.objects.create_user("cust", password="x", role="customer")
        cls.space = Space.objects.create(name="Ops")

    def post(self, owner):
        self.client.force_login(self.agent)
        return self.client.post(
            reverse("wiki:page_new"),
            {"title": "Owned", "body": "x", "space": self.space.slug, "owner": owner},
        )

    def test_new_page_saves_its_owner(self):
        self.post(str(self.agent.pk))
        self.assertEqual(Page.objects.get(title="Owned").owner, self.agent)

    def test_a_customer_cannot_own_a_page(self):
        response = self.post(str(self.customer.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pick someone on the team")
        self.assertFalse(Page.objects.filter(title="Owned").exists())

    def test_the_editor_defaults_the_owner_to_whoever_starts_the_page(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("wiki:page_new"))
        self.assertContains(response, f'<option value="{self.agent.pk}" selected>')

"""Suggested articles: what the wiki thinks an agent should read for a ticket.

The KB migration seeds wiki pages whose titles are ordinary words — "Reset your
password" and friends — so the word-match tests use topics that migration could
never contain, and each asserts on the order of its own pages rather than on the
head of a list the import also feeds.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.items.models import Item, ItemKind
from apps.links.service import add_link
from apps.tickets.models import Ticket
from apps.wiki.models import Page, Space
from apps.wiki.service import suggest_pages


class SuggestPagesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.customer = User.objects.create_user("cust1", password="x", role="customer")
        cls.space = Space.objects.create(name="Suggestions test space")
        cls.server = ItemKind.objects.get(name="Server")

    def page(self, title, *, body="", summary=""):
        return Page.objects.create(
            space=self.space, title=title, body=body or f"{title} steps", summary=summary
        )

    def ticket(self, title):
        return Ticket.objects.create(title=title, description="body", created_by=self.agent)

    def suggest(self, ticket, limit=3, user=None):
        return [page.title for page in suggest_pages(ticket, user or self.agent, limit=limit)]

    def test_linked_page_comes_first(self):
        # A linked page is a decision someone already made; a word match only
        # guesses. Recency is what a word match falls back on, not the ranking.
        ticket = self.ticket("Zabbix trigger fires on the collector host")
        stale = self.page("Rotate a collector host key")
        linked = self.page("Collector host inventory", body="collector hosts and keys")
        Page.objects.filter(pk=stale.pk).update(updated_at=timezone.now() - timedelta(days=9))
        add_link(self.agent, ("ticket", str(ticket.pk)), ("page", str(linked.pk)), "relates_to")

        self.assertEqual(self.suggest(ticket, limit=1), ["Collector host inventory"])
        self.assertEqual(
            self.suggest(ticket, limit=2),
            ["Collector host inventory", "Rotate a collector host key"],
        )

    def test_page_linked_to_a_linked_item_is_suggested(self):
        ticket = self.ticket("Wireguard tunnels keep dropping on the concentrator")
        item = Item.objects.create(name="Wireguard concentrator", kind=self.server)
        runbook = self.page("Wireguard concentrator runbook", body="reboot it")
        add_link(self.agent, ("ticket", str(ticket.pk)), ("item", str(item.pk)), "relates_to")
        add_link(self.agent, ("item", str(item.pk)), ("page", str(runbook.pk)), "relates_to")

        self.assertEqual(self.suggest(ticket, limit=1), ["Wireguard concentrator runbook"])

    def test_word_match_prefers_title_hits(self):
        # "Bunk rooms" hits one word in its body; "Rota rebooking" hits one in
        # its title, which is worth three — the word the author put in the title
        # is the one they meant.
        ticket = self.ticket("Rebook the bunk room for the night shift rota")
        self.page("Bunk rooms", body="the night shift rota sleeps here")
        title_hit = self.page("Shift rota", summary="booking the bunks again")

        suggestions = self.suggest(ticket, limit=2)

        self.assertEqual(suggestions[0], title_hit.title)
        self.assertIn("Bunk rooms", suggestions)
        self.assertLess(suggestions.index("Shift rota"), suggestions.index("Bunk rooms"))
        self.assertEqual(len(suggestions), len(set(suggestions)))

    def test_a_stop_word_never_matches_a_page(self):
        ticket = self.ticket("Cannot connect with your laptop")
        self.page("About your account", summary="cannot, with, your, about")

        self.assertEqual(self.suggest(ticket), [])

    def test_customer_gets_no_suggestions(self):
        ticket = self.ticket("Kibble store is overflowing")
        page = self.page("Kibble store sizing", body="empty the kibble store")
        add_link(self.agent, ("ticket", str(ticket.pk)), ("page", str(page.pk)), "relates_to")

        self.assertEqual(suggest_pages(ticket, self.customer), [])
        self.assertEqual(suggest_pages(ticket, self.customer, limit=5), [])

    def test_at_most_the_limit_and_nothing_repeated(self):
        ticket = self.ticket("Kibble store is overflowing")
        first = self.page("Kibble stores", body="overflowing kibble")
        add_link(self.agent, ("ticket", str(ticket.pk)), ("page", str(first.pk)), "relates_to")
        self.page("Overflow bins", summary="kibble and store")
        self.page("Store rooms", summary="kibble and store")
        self.page("Storekeeping", summary="kibble and store")

        suggestions = self.suggest(ticket, limit=3)

        self.assertEqual(len(suggestions), 3)
        self.assertEqual(suggestions[0], "Kibble stores")
        self.assertEqual(len(suggestions), len(set(suggestions)))

    def test_a_ticket_with_nothing_to_suggest_returns_nothing(self):
        self.assertEqual(self.suggest(self.ticket("Hi there")), [])


class SuggestedArticlesCardTest(TestCase):
    """The card on the ticket page, and the button that quotes a page in a reply."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.customer = User.objects.create_user("cust1", password="x", role="customer")
        cls.space = Space.objects.create(name="Suggestions card test space")

    def page(self, title, *, body="", summary=""):
        return Page.objects.create(
            space=self.space, title=title, body=body or f"{title} steps", summary=summary
        )

    def test_ticket_page_shows_the_card_for_staff_only(self):
        owner = User.objects.create_user("cust2", password="x", role="customer")
        ticket = Ticket.objects.create(
            title="Wireguard tunnels keep dropping", description="body", created_by=owner
        )
        page = self.page("Wireguard laptop setup", body="install the client")
        page.is_published_to_help_center = True
        page.save()
        add_link(self.agent, ("ticket", str(ticket.pk)), ("page", str(page.pk)), "relates_to")
        url = reverse("tickets:ticket_detail", args=[ticket.pk])
        help_url = reverse("help:article", args=[page.slug])

        self.client.force_login(self.agent)
        staff = self.client.get(url).content.decode()
        self.assertIn("Suggested articles", staff)
        self.assertIn(page.get_absolute_url(), staff)
        self.assertIn("Insert link", staff)
        # The absolute URL is what a reply quotes, and "data-insert-article" is
        # the selector the click handler finds the button with: without it the
        # card renders buttons that do nothing at all when clicked.
        # A reply goes to a customer, so it quotes the help center, not /wiki/.
        self.assertIn(f'data-article-url="http://testserver{help_url}"', staff)
        self.assertIn("data-insert-article", staff)
        self.assertIn("data-article-title=", staff)

        self.client.force_login(owner)
        customer = self.client.get(url).content.decode()
        self.assertNotIn("Suggested articles", customer)
        self.assertNotIn("data-insert-article", customer)

    def test_an_internal_page_is_suggested_but_never_offered_as_a_link(self):
        ticket = Ticket.objects.create(
            title="Wireguard tunnels keep dropping", description="body", created_by=self.agent
        )
        page = self.page("Wireguard internal runbook", body="agents only")
        add_link(self.agent, ("ticket", str(ticket.pk)), ("page", str(page.pk)), "relates_to")
        self.client.force_login(self.agent)
        html = self.client.get(reverse("tickets:ticket_detail", args=[ticket.pk])).content.decode()
        self.assertIn("Wireguard internal runbook", html)
        self.assertIn("Internal", html)
        self.assertNotIn("data-article-url=", html)

    def test_no_card_when_there_is_nothing_to_suggest(self):
        owner = User.objects.create_user("cust3", password="x", role="customer")
        ticket = Ticket.objects.create(title="Hi there", description="?", created_by=owner)
        self.client.force_login(self.agent)
        body = self.client.get(reverse("tickets:ticket_detail", args=[ticket.pk])).content.decode()

        self.assertNotIn("Suggested articles", body)
        self.assertNotIn("data-insert-article", body)

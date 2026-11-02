"""The real vigil:* resolvers and an Item's live Vigil host."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.accounts.models import User
from apps.items.models import Item, ItemKind
from apps.links.registry import get_resolver
from apps.links.service import add_link, links_for
from apps.tickets.models import Ticket
from apps.vigil import hosts as vigil_hosts
from apps.vigil import links as vigil_links
from apps.vigil.client import VigilUnavailable
from apps.vigil.links import DOWN_KEY, VigilResolver


class FakeClient:
    def __init__(self, items=None, results=None, host=None):
        self.items = items if items is not None else {}
        self.results = results if results is not None else []
        self.host = host
        self.resolve_calls = []
        self.search_calls = []
        self.detail_calls = []

    def resolve(self, type, ids):
        self.resolve_calls.append((type, list(ids)))
        if isinstance(self.items, Exception):
            raise self.items
        return {i: self.items[i] for i in ids if i in self.items}

    def search(self, q, type=None):
        self.search_calls.append((q, type))
        if isinstance(self.results, Exception):
            raise self.results
        return self.results

    def detail(self, type, id):
        self.detail_calls.append((type, id))
        if isinstance(self.host, Exception):
            raise self.host
        return self.host


HOST_ITEM = {
    "type": "host",
    "id": "42",
    "label": "mail-01",
    "sub": "10.20.4.11",
    "status": "Online",
    "tone": "ok",
    "url": "https://vigil.example.gov/#open/host/42",
}

TASK_ITEM = {
    "type": "task",
    "id": "7",
    "label": "Renew the TLS cert",
    "status": "Open",
    "tone": "loud",
    "url": "https://vigil.example.gov/#open/task/7",
}


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class ResolverTests(TestCase):
    def setUp(self):
        cache.clear()
        self.agent = make_user("aria", "agent")
        self.customer = make_user("boa", "customer")

    def test_resolve_returns_real_targets_with_status_and_url(self):
        fake = FakeClient(items={"42": HOST_ITEM})
        with patch.object(vigil_links, "get_client", return_value=fake):
            targets = VigilResolver("host").resolve(["42"], self.agent)

        self.assertEqual(list(targets), ["42"])
        target = targets["42"]
        self.assertTrue(target.available)
        self.assertEqual(target.label, "mail-01")
        self.assertEqual(target.status, "Online")
        self.assertEqual(target.tone, "ok")
        self.assertEqual(target.url, "https://vigil.example.gov/#open/host/42")

    def test_resolve_hides_ids_vigil_does_not_return(self):
        fake = FakeClient(items={"42": HOST_ITEM})
        with patch.object(vigil_links, "get_client", return_value=fake):
            targets = VigilResolver("host").resolve(["42", "99"], self.agent)

        self.assertEqual(list(targets), ["42"])
        self.assertEqual(fake.resolve_calls, [("host", ["42", "99"])])

    def test_vigil_down_marks_chips_unavailable_and_stops_calling(self):
        fake = FakeClient(items=VigilUnavailable("Can't reach Vigil at vigil.example.gov."))
        with patch.object(vigil_links, "get_client", return_value=fake):
            first = VigilResolver("host").resolve(["42"], self.agent)

        self.assertFalse(first["42"].available)
        self.assertEqual(first["42"].status, "Vigil unavailable")
        self.assertEqual(first["42"].tone, "muted")

        with patch.object(vigil_links, "get_client", return_value=fake):
            second = VigilResolver("task").resolve(["7"], self.agent)

        self.assertEqual(len(fake.resolve_calls), 1, "the second call must not reach Vigil")
        self.assertEqual(second["7"].status, "Vigil unavailable")

    def test_not_configured_reads_vigil_not_connected(self):
        with patch.object(vigil_links, "get_client", return_value=None):
            targets = VigilResolver("host").resolve(["42"], self.agent)

        self.assertFalse(targets["42"].available)
        self.assertEqual(targets["42"].status, "Vigil not connected")
        self.assertEqual(targets["42"].label, "42")

    def test_customer_gets_nothing(self):
        fake = FakeClient(items={"42": HOST_ITEM})
        with patch.object(vigil_links, "get_client", return_value=fake):
            self.assertEqual(VigilResolver("host").resolve(["42"], self.customer), {})
            self.assertEqual(VigilResolver("host").search("mail", self.customer, 5), [])
        self.assertEqual(fake.resolve_calls, [])

    def test_search_calls_vigil_once_for_all_kinds(self):
        fake = FakeClient(results=[HOST_ITEM, TASK_ITEM])
        with patch.object(vigil_links, "get_client", return_value=fake):
            hosts = VigilResolver("host").search("Mail", self.agent, 5)
            tasks = VigilResolver("task").search("mail", self.agent, 5)

        self.assertEqual(len(fake.search_calls), 1)
        self.assertEqual(fake.search_calls[0], ("Mail", None))
        self.assertEqual([t.label for t in hosts], ["mail-01"])
        self.assertEqual([t.id for t in tasks], ["7"])

    def test_unknown_tone_is_dropped(self):
        fake = FakeClient(items={"7": TASK_ITEM})
        with patch.object(vigil_links, "get_client", return_value=fake):
            target = VigilResolver("task").resolve(["7"], self.agent)["7"]

        self.assertEqual(target.tone, "")

    def test_from_url_reads_a_vigil_deep_link_for_its_kind_only(self):
        with patch.object(vigil_links, "VigilConnection") as connection:
            connection.get_solo.return_value.base_url = "https://vigil.example.gov"
            self.assertEqual(
                VigilResolver("host").from_url("https://vigil.example.gov/#open/host/42"), "42"
            )
            self.assertIsNone(
                VigilResolver("task").from_url("https://vigil.example.gov/#open/host/42")
            )
            self.assertIsNone(VigilResolver("host").from_url("http://other.test/#open/host/42"))

        with patch.object(vigil_links, "VigilConnection") as connection:
            connection.get_solo.return_value.base_url = ""
            self.assertIsNone(
                VigilResolver("host").from_url("https://vigil.example.gov/#open/host/42")
            )

    def test_registered_types_are_vigil_resolvers(self):
        for kind in ("host", "task", "playbook", "run", "automation"):
            with self.subTest(kind=kind):
                self.assertIsInstance(get_resolver(f"vigil:{kind}"), VigilResolver)

    def test_down_link_keeps_the_cached_label(self):
        ticket = Ticket.objects.create(
            title="Mail is down", description="body", created_by=self.agent
        )
        fake = FakeClient(items={"42": HOST_ITEM})
        with patch.object(vigil_links, "get_client", return_value=fake):
            link = add_link(self.agent, ("ticket", str(ticket.pk)), ("vigil:host", "42"))

        down = FakeClient(items=VigilUnavailable("Can't reach Vigil at vigil.example.gov."))
        with patch.object(vigil_links, "get_client", return_value=down):
            views = links_for("ticket", str(ticket.pk), self.agent)

        self.assertEqual(len(views), 1)
        self.assertFalse(views[0].other.available)
        self.assertEqual(views[0].other.label, "mail-01")
        self.assertEqual(views[0].other.status, "Vigil unavailable")
        self.assertEqual(down.resolve_calls, [("host", ["42"])])
        self.assertTrue(link.pk)


class ItemHostTests(TestCase):
    def setUp(self):
        cache.clear()
        self.agent = make_user("aria", "agent")
        self.admin = make_user("coral", "admin")
        self.customer = make_user("boa", "customer")
        self.server = ItemKind.objects.get(name="Server")
        self.url = "/items/"

    def make_item(self, **kwargs):
        kwargs.setdefault("name", "Mail server")
        kwargs.setdefault("kind", self.server)
        return Item.objects.create(**kwargs)

    def test_item_shows_live_host_and_open_in_vigil(self):
        self.client.force_login(self.agent)
        item = self.make_item(vigil_host_id="42")
        fake = FakeClient(host=HOST_ITEM)
        with patch.object(vigil_hosts, "get_client", return_value=fake):
            response = self.client.get(f"/items/{item.pk}/")

        self.assertContains(response, "mail-01")
        self.assertContains(response, "Online")
        self.assertContains(response, 'href="https://vigil.example.gov/#open/host/42"')
        self.assertContains(response, "Open in Vigil")
        self.assertEqual(fake.detail_calls, [("host", "42")])

    def test_item_suggests_a_host_by_attribute_and_links_it(self):
        self.client.force_login(self.agent)
        item = self.make_item(attributes={"Host": "mail-01"})
        fake = FakeClient(results=[HOST_ITEM], host=HOST_ITEM)
        with patch.object(vigil_hosts, "get_client", return_value=fake):
            response = self.client.get(f"/items/{item.pk}/")

        self.assertContains(response, "Looks like mail-01")
        self.assertContains(response, "Link this host")
        self.assertEqual(fake.search_calls[0], ("mail-01", "host"))

        with patch("apps.items.views.get_client", return_value=fake):
            response = self.client.post(
                f"/items/{item.pk}/vigil-host/", {"host_id": "42"}, follow=True
            )

        item.refresh_from_db()
        self.assertEqual(item.vigil_host_id, "42")
        messages = [(m.level_tag, str(m)) for m in response.context["messages"]]
        self.assertIn(("success", "Linked to Vigil host mail-01."), messages)

    def test_item_page_loads_when_vigil_is_down(self):
        self.client.force_login(self.agent)
        item = self.make_item(vigil_host_id="42")
        fake = FakeClient(host=VigilUnavailable("Can't reach Vigil at vigil.example.gov."))
        with patch.object(vigil_hosts, "get_client", return_value=fake):
            response = self.client.get(f"/items/{item.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vigil unavailable")
        self.assertEqual(cache.get(DOWN_KEY), "Can't reach Vigil at vigil.example.gov.")

    def test_link_host_requires_edit_permission(self):
        item = self.make_item()
        self.client.force_login(self.customer)
        response = self.client.post(f"/items/{item.pk}/vigil-host/", {"host_id": "42"})
        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.vigil_host_id, "")

    def test_unlink_clears_the_host(self):
        item = self.make_item(vigil_host_id="42")
        self.client.force_login(self.agent)
        with patch.object(vigil_hosts, "get_client", return_value=None):
            response = self.client.post(
                f"/items/{item.pk}/vigil-host/", {"host_id": ""}, follow=True
            )

        item.refresh_from_db()
        self.assertEqual(item.vigil_host_id, "")
        messages = [(m.level_tag, str(m)) for m in response.context["messages"]]
        self.assertIn(("success", "Vigil host cleared."), messages)

    def test_link_host_with_vigil_down_still_links_and_says_the_id(self):
        self.client.force_login(self.agent)
        item = self.make_item()
        fake = FakeClient(host=VigilUnavailable("Can't reach Vigil at vigil.example.gov."))
        with patch("apps.items.views.get_client", return_value=fake):
            response = self.client.post(
                f"/items/{item.pk}/vigil-host/", {"host_id": "42"}, follow=True
            )

        item.refresh_from_db()
        self.assertEqual(item.vigil_host_id, "42")
        messages = [(m.level_tag, str(m)) for m in response.context["messages"]]
        self.assertIn(("success", "Linked to Vigil host 42."), messages)

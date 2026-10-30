"""The links API: what the endpoints return, and who may call them."""

from contextlib import contextmanager

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.items.models import Item, ItemKind
from apps.links import registry
from apps.links.registry import LinkTarget, Resolver, register_type
from apps.links.service import add_link
from apps.tickets.models import Ticket


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class EmptyResolver(Resolver):
    """A registered type with nothing to find: the shape of a remote resolver
    before anything is connected behind it."""

    def resolve(self, ids, user):
        return {}

    def search(self, q, user, limit):
        return []


class UnreachableResolver(Resolver):
    """A type whose objects are there but not connected — a remote stub that
    answers with an unavailable target."""

    def resolve(self, ids, user):
        return {i: LinkTarget(type="temp:far", id=i, label=i, available=False) for i in ids}

    def search(self, q, user, limit):
        return [LinkTarget(type="temp:far", id="mx-01", label="mx-01", available=False)]


@contextmanager
def temporary_type(name, resolver):
    register_type(name, resolver)
    try:
        yield name
    finally:
        registry._TYPES.pop(name, None)


class LinksApiTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.customer = make_user("boa", "customer")
        self.server = ItemKind.objects.get(name="Server")
        self.mail_ticket = Ticket.objects.create(
            title="Mail is bouncing", description="body", created_by=self.agent
        )
        self.mail_item = Item.objects.create(name="Mail server", kind=self.server)
        self.other = Ticket.objects.create(
            title="Printer jammed again", description="body", created_by=self.agent
        )

    def _get(self, user, name, *args, **query):
        self.client.force_login(user)
        url = reverse(name, args=args)
        if query:
            url = url + "?" + "&".join(f"{k}={v}" for k, v in query.items())
        return self.client.get(url)

    def _add(self, user, **overrides):
        payload = {
            "source_type": "ticket",
            "source_id": str(self.mail_ticket.pk),
            "target_type": "item",
            "target_id": str(self.mail_item.pk),
            "relation": "caused_by",
        }
        payload.update(overrides)
        self.client.force_login(user)
        return self.client.post(
            reverse("links:links-add"), data=payload, content_type="application/json"
        )

    def test_for_returns_links_and_relations(self):
        link = add_link(
            self.agent,
            ("ticket", str(self.mail_ticket.pk)),
            ("item", str(self.mail_item.pk)),
            "affects",
        )
        body = self._get(self.agent, "links:links-for", "ticket", str(self.mail_ticket.pk)).json()
        self.assertEqual(
            [(row["link_id"], row["relation"], row["label"]) for row in body["links"]],
            [(link.pk, "affects", "affects")],
        )
        other = body["links"][0]["other"]
        self.assertEqual(other["type"], "item")
        self.assertEqual(other["id"], str(self.mail_item.pk))
        self.assertEqual(other["label"], "Mail server")
        self.assertEqual(other["url"], f"/items/{self.mail_item.pk}/")

        relations = {row[0]: (row[1], row[2]) for row in body["relations"]}
        self.assertEqual(relations["fixed_by"], ("fixed by", "fixes"))

        from_item = self._get(self.agent, "links:links-for", "item", str(self.mail_item.pk)).json()
        self.assertEqual([row["label"] for row in from_item["links"]], ["affected by"])

    def test_add_and_remove_round_trip(self):
        resp = self._add(self.agent)
        self.assertEqual(resp.status_code, 201)
        created = resp.json()
        self.assertEqual(created["relation"], "caused_by")
        self.assertEqual(created["label"], "caused by")
        self.assertEqual(created["other"]["label"], "Mail server")

        removed = self.client.post(
            reverse("links:links-remove", args=[created["link_id"]]),
            content_type="application/json",
        )
        self.assertEqual(removed.status_code, 204)
        links = self._get(self.agent, "links:links-for", "ticket", str(self.mail_ticket.pk)).json()
        self.assertEqual(links["links"], [])

    def test_add_defaults_to_relates_to(self):
        created = self._add(self.agent, relation="").json()
        self.assertEqual(created["relation"], "relates_to")
        self.assertEqual(created["label"], "relates to")

    def test_add_error_is_400_with_message(self):
        resp = self._add(
            self.agent,
            target_type="ticket",
            target_id=str(self.mail_ticket.pk),
            relation="relates_to",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "A thing cannot link to itself.")

    def test_search_spans_types_and_excludes_self(self):
        resp = self._get(
            self.agent,
            "links:links-search",
            q="mail",
            exclude_type="ticket",
            exclude_id=str(self.mail_ticket.pk),
        )
        self.assertEqual(resp.status_code, 200)
        found = {(row["type"], row["label"]) for row in resp.json()["results"]}
        self.assertIn(("item", "Mail server"), found)
        self.assertNotIn(("ticket", f"#{self.mail_ticket.pk} Mail is bouncing"), found)

    def test_search_needs_two_characters(self):
        self.assertEqual(self._get(self.agent, "links:links-search", q="m").json()["results"], [])
        self.assertEqual(self._get(self.agent, "links:links-search").json()["results"], [])

    def test_search_leaves_out_types_with_nothing_behind_them(self):
        with temporary_type("temp:nowhere", EmptyResolver()) as name:
            found = {row["type"] for row in self._search("anything")}
            self.assertNotIn(name, found)

    def test_search_never_offers_an_unavailable_target(self):
        with temporary_type("temp:far", UnreachableResolver()) as name:
            found = {row["type"]: row for row in self._search("mx")}
            self.assertNotIn(name, found)

    def test_search_offers_every_type_that_has_objects(self):
        # Both kinds hold a "mail" object; the picker answers with both.
        found = {(row["type"], row["id"]) for row in self._search("mail")}
        self.assertIn(("ticket", str(self.mail_ticket.pk)), found)
        self.assertIn(("item", str(self.mail_item.pk)), found)

    def test_search_names_each_type_in_words(self):
        labels = {row["type"]: row["type_label"] for row in self._search("mail")}
        self.assertEqual(labels["ticket"], "Tickets")
        self.assertEqual(labels["item"], "Dynamic Items")

    def test_type_label_reads_vigil_kinds_and_unknown_types(self):
        from .registry import type_label

        self.assertEqual(type_label("card"), "Issues")
        self.assertEqual(type_label("vigil:host"), "Vigil hosts")
        self.assertEqual(type_label("asset_tag"), "Asset tag")

    def _search(self, term):
        resp = self._get(self.agent, "links:links-search", q=term)
        return resp.json()["results"]

    def test_resolve_url_for_ticket_and_item(self):
        ticket = self._get(
            self.agent,
            "links:links-resolve-url",
            url=f"https://x.test/tickets/{self.other.pk}/",
        )
        self.assertEqual(ticket.status_code, 200)
        self.assertEqual(ticket.json()["target"]["type"], "ticket")
        self.assertEqual(ticket.json()["target"]["id"], str(self.other.pk))

        item = self._get(self.agent, "links:links-resolve-url", url=f"/items/{self.mail_item.pk}/")
        self.assertEqual(item.status_code, 200)
        self.assertEqual(item.json()["target"]["label"], "Mail server")

    def test_resolve_url_unknown_is_404(self):
        for url in ("/tickets/999999/", "/nonsense/", ""):
            with self.subTest(url=url):
                resp = self._get(self.agent, "links:links-resolve-url", url=url)
                self.assertEqual(resp.status_code, 404)
                self.assertEqual(
                    resp.json()["error"], "That link doesn't point at anything Jackil knows."
                )

    def test_customer_gets_403_from_every_endpoint(self):
        self.client.force_login(self.customer)
        calls = [
            ("get", reverse("links:links-for", args=["ticket", str(self.mail_ticket.pk)])),
            ("post", reverse("links:links-add")),
            ("post", reverse("links:links-remove", args=[1])),
            ("get", reverse("links:links-search") + "?q=mail"),
            ("get", reverse("links:links-resolve-url") + "?url=/tickets/1/"),
        ]
        for method, url in calls:
            with self.subTest(url=url):
                resp = getattr(self.client, method)(url)
                self.assertEqual(resp.status_code, 403)

"""Items — the register, its pages, permissions and the `item` link type."""

import re
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import Department, User
from apps.items.forms import parse_attributes
from apps.items.links import ItemResolver
from apps.items.models import Item, ItemKind
from apps.links import registry
from apps.links.service import add_link, links_for

DEFAULT_KIND_NAMES = [
    "Server",
    "Application",
    "Service",
    "Network device",
    "Licence",
    "Other",
]

#: The forbidden words live as fragments so this file can't trip its own check.
FORBIDDEN = re.compile("C" + "MDB|" + "configuration " + "item|" + r"\bC" + "Is?\b")


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class ItemModelTests(TestCase):
    def test_default_kinds_exist(self):
        self.assertEqual([kind.name for kind in ItemKind.objects.all()], DEFAULT_KIND_NAMES)

    def test_kind_slug_is_filled(self):
        kind = ItemKind.objects.create(name="Rack Unit")
        self.assertEqual(kind.slug, "rack-unit")


class ItemViewTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.admin = make_user("coral", "admin")
        self.customer = make_user("boa", "customer")
        self.server = ItemKind.objects.get(name="Server")
        self.service = ItemKind.objects.get(name="Service")
        self.mail = Item.objects.create(name="Mail server", kind=self.server, vendor="Acme")
        self.dept = Department.objects.create(name="IT")

    def _create_payload(self, **overrides):
        payload = {
            "name": "File server",
            "kind": self.service.pk,
            "owner": "",
            "department": self.dept.pk,
            "vendor": "Globex",
            "warranty_end": "2027-01-31",
            "notes": "rack B4",
            "vigil_host_id": "",
            "attributes_text": "Serial: X1",
        }
        payload.update(overrides)
        return payload

    def test_agent_can_list_create_view_and_edit(self):
        self.client.force_login(self.agent)

        listed = self.client.get(reverse("items:item_list"))
        self.assertEqual(listed.status_code, 200)
        self.assertContains(listed, "Mail server")

        created = self.client.post(reverse("items:item_create"), self._create_payload())
        self.assertEqual(created.status_code, 302)
        item = Item.objects.get(name="File server")
        self.assertEqual(item.kind, self.service)
        self.assertEqual(item.warranty_end, date(2027, 1, 31))
        self.assertEqual(item.attributes, {"Serial": "X1"})

        detail = self.client.get(item.get_absolute_url())
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "File server")
        self.assertContains(detail, "Globex")

        edited = self.client.post(
            reverse("items:item_edit", args=[item.pk]),
            self._create_payload(name="File server v2"),
        )
        self.assertEqual(edited.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.name, "File server v2")

    def test_agent_cannot_delete(self):
        self.client.force_login(self.agent)
        url = reverse("items:item_delete", args=[self.mail.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(Item.objects.filter(pk=self.mail.pk).exists())

    def test_kind_page_carries_a_token_the_browser_can_post(self):
        # The inline add-kind form posts back to the same URL, so a token in
        # its own body is what makes the browser's POST acceptable.
        self.client.force_login(self.admin)
        page = self.client.get(reverse("items:kind_list"))
        self.assertEqual(page.status_code, 200)
        self.assertIn('name="csrfmiddlewaretoken"', page.content.decode())

    def test_admin_can_delete(self):
        self.client.force_login(self.admin)
        url = reverse("items:item_delete", args=[self.mail.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url)
        self.assertFalse(Item.objects.filter(pk=self.mail.pk).exists())

    def test_customer_gets_403_everywhere(self):
        self.client.force_login(self.customer)
        urls = [
            reverse("items:item_list"),
            reverse("items:item_create"),
            reverse("items:item_detail", args=[self.mail.pk]),
            reverse("items:item_edit", args=[self.mail.pk]),
            reverse("items:item_delete", args=[self.mail.pk]),
            reverse("items:kind_list"),
            reverse("items:kind_delete", args=[self.server.pk]),
        ]
        for url in urls:
            for method in ("get", "post"):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("items:item_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])

    def test_search_and_kind_filter(self):
        self.client.force_login(self.agent)
        Item.objects.create(name="Backup NAS", kind=self.service, vendor="Acme")
        Item.objects.create(name="Printer fleet", kind=self.service, notes="floor 3")

        by_name = self.client.get(reverse("items:item_list"), {"q": "mail"})
        self.assertContains(by_name, "Mail server")
        self.assertNotContains(by_name, "Printer fleet")

        by_vendor = self.client.get(reverse("items:item_list"), {"q": "acme"})
        self.assertContains(by_vendor, "Mail server")
        self.assertContains(by_vendor, "Backup NAS")
        self.assertNotContains(by_vendor, "Printer fleet")

        by_notes = self.client.get(reverse("items:item_list"), {"q": "floor 3"})
        self.assertContains(by_notes, "Printer fleet")

        by_kind = self.client.get(reverse("items:item_list"), {"kind": "server"})
        self.assertContains(by_kind, "Mail server")
        self.assertNotContains(by_kind, "Backup NAS")

    def test_attributes_round_trip(self):
        self.client.force_login(self.agent)
        self.client.post(
            reverse("items:item_create"),
            self._create_payload(attributes_text="Serial: X1\nRack: B4\n\nbad line"),
        )
        item = Item.objects.get(name="File server")
        self.assertEqual(item.attributes, {"Serial": "X1", "Rack": "B4"})

        form_page = self.client.get(reverse("items:item_edit", args=[item.pk]))
        self.assertContains(form_page, "Serial: X1")

    def test_too_many_attributes_is_a_form_error(self):
        self.client.force_login(self.agent)
        text = "\n".join(f"Key {i}: v" for i in range(51))
        response = self.client.post(
            reverse("items:item_create"), self._create_payload(attributes_text=text)
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at most 50 attributes")
        self.assertFalse(Item.objects.filter(name="File server").exists())

    def test_kind_with_items_cannot_be_deleted(self):
        self.client.force_login(self.admin)
        url = reverse("items:kind_delete", args=[self.server.pk])
        response = self.client.post(url, follow=True)
        self.assertTrue(ItemKind.objects.filter(pk=self.server.pk).exists())
        self.assertContains(response, "still has Items")

        empty = ItemKind.objects.get(name="Licence")
        self.client.post(reverse("items:kind_delete", args=[empty.pk]))
        self.assertFalse(ItemKind.objects.filter(pk=empty.pk).exists())

    def test_only_admin_manages_kinds(self):
        url = reverse("items:kind_list")
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.post(url, {"name": "Router", "icon_color": "sky"}).status_code, 403
        )

        self.client.force_login(self.admin)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        added = self.client.post(url, {"name": "Network appliance", "icon_color": "mint"})
        self.assertEqual(added.status_code, 302)
        kind = ItemKind.objects.get(name="Network appliance")
        self.assertEqual(kind.slug, "network-appliance")

        after_delete = self.client.post(reverse("items:kind_delete", args=[kind.pk]))
        self.assertEqual(after_delete.status_code, 302)
        self.assertFalse(ItemKind.objects.filter(pk=kind.pk).exists())


class ItemLinkTypeTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.customer = make_user("boa", "customer")
        self.kind = ItemKind.objects.get(name="Server")
        self.item = Item.objects.create(name="Mail server", kind=self.kind, vendor="Acme")

    def test_item_type_is_registered(self):
        self.assertIn("item", registry.types())
        self.assertIsInstance(registry.get_resolver("item"), ItemResolver)

    def test_resolve_hides_items_from_customers(self):
        targets = registry.get_resolver("item").resolve([str(self.item.pk)], self.agent)
        target = targets[str(self.item.pk)]
        self.assertEqual(target.label, "Mail server")
        self.assertEqual(target.url, f"/items/{self.item.pk}/")
        self.assertEqual(target.status, "Server")
        self.assertEqual(target.tone, "info")

        customer = registry.get_resolver("item").resolve([str(self.item.pk)], self.customer)
        self.assertEqual(customer, {})
        searches = registry.get_resolver("item").search("mail", self.customer, limit=5)
        self.assertEqual(searches, [])

    def test_search_by_name_and_vendor(self):
        resolver = registry.get_resolver("item")
        nas = Item.objects.create(name="Backup NAS", kind=self.kind, vendor="Acme")
        Item.objects.create(name="Printer fleet", kind=self.kind)

        hits = resolver.search("mail", self.agent, limit=5)
        self.assertEqual([t.id for t in hits], [str(self.item.pk)])

        by_vendor = resolver.search("acme", self.agent, limit=5)
        self.assertEqual(sorted(t.id for t in by_vendor), sorted([str(self.item.pk), str(nas.pk)]))

        self.assertEqual(resolver.search("no match", self.agent, limit=5), [])
        self.assertEqual(len(resolver.search("a", self.agent, limit=1)), 1)

    def test_from_url(self):
        resolver = ItemResolver()
        self.assertEqual(resolver.from_url("http://jackil.local/items/7/"), "7")
        self.assertEqual(resolver.from_url("/items/7/"), "7")
        self.assertIsNone(resolver.from_url("/items/7/edit/"))
        self.assertIsNone(resolver.from_url("/tickets/7/"))

    def test_ticket_can_link_to_item(self):
        from apps.tickets.models import Ticket

        ticket = Ticket.objects.create(
            title="Mail is down", description="body", created_by=self.agent
        )
        add_link(
            self.agent,
            ("ticket", str(ticket.pk)),
            ("item", str(self.item.pk)),
            "affects",
        )

        from_ticket = links_for("ticket", str(ticket.pk), self.agent)
        self.assertEqual(
            [(v.label, v.other.type, v.other.id) for v in from_ticket],
            [("affects", "item", str(self.item.pk))],
        )

        from_item = links_for("item", str(self.item.pk), self.agent)
        self.assertEqual([(v.label, v.other.type) for v in from_item], [("affected by", "ticket")])


class SidebarTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.customer = make_user("boa", "customer")

    def test_staff_sidebar_has_items(self):
        self.client.force_login(self.agent)
        page = self.client.get(reverse("tickets:ticket_list"))
        self.assertContains(page, 'data-tip="Items"')
        self.assertContains(page, "/items/")

    def test_customer_sidebar_has_no_items(self):
        self.client.force_login(self.customer)
        page = self.client.get(reverse("tickets:customer_tickets"))
        self.assertNotContains(page, 'data-tip="Items"')


class NamingTests(SimpleTestCase):
    def test_no_forbidden_words(self):
        root = Path(__file__).resolve().parent
        checked = 0
        for path in sorted(root.rglob("*.py")) + sorted((root / "templates").rglob("*.html")):
            if path.name == "tests.py" or "migrations" in path.parts:
                continue
            checked += 1
            self.assertIsNone(
                FORBIDDEN.search(path.read_text(encoding="utf-8")),
                f"{path.name} names the feature wrongly",
            )
        self.assertGreater(checked, 5)


class AttributeParsingTests(SimpleTestCase):
    def test_lines_without_a_key_are_skipped(self):
        self.assertEqual(
            parse_attributes("Serial: X1\nRack: B4\n\nbad line\n: no key"),
            {"Serial": "X1", "Rack": "B4"},
        )

    def test_value_may_contain_colons(self):
        self.assertEqual(parse_attributes("URL: http://x:8080"), {"URL": "http://x:8080"})

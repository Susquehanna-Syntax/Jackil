"""Dynamic Items — the wording, the kind tabs, the quick chips and card grid."""

import re
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.items.models import Item, ItemKind
from apps.links.service import add_link
from apps.tickets.models import Ticket


def make_user(username):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role="agent")


class DynamicItemsWordingTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria")
        self.client.force_login(self.agent)
        self.server = ItemKind.objects.get(name="Server")
        Item.objects.create(name="Mail server", kind=self.server)

    def test_page_says_dynamic_items(self):
        page = self.client.get(reverse("items:item_list"))
        self.assertContains(page, "Dynamic Items")
        self.assertContains(page, "New Dynamic Item")


class KindTabTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria")
        self.client.force_login(self.agent)
        self.server = ItemKind.objects.get(name="Server")
        Item.objects.create(name="Mail server", kind=self.server)

    def test_tabs_list_kinds_with_counts_and_all_first(self):
        page = self.client.get(reverse("items:item_list"))
        body = page.content.decode()
        self.assertIn('data-live-tab=""', body)
        self.assertIn("1 item", body)
        server_tab = body.index('href="?kind=server"')
        all_tab = body.index('data-live-tab=""')
        self.assertLess(all_tab, server_tab)
        self.assertIn('href="?kind=server"', body)
        self.assertIn('data-live-tab="server"', body)

    def test_lavender_kind_gets_lav_tab_colour(self):
        page = self.client.get(reverse("items:item_list"))
        self.assertContains(page, 'class="tab t-lav" href="?kind=application"')


class ChipTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria")
        self.colleague = make_user("coral")
        self.client.force_login(self.agent)
        self.server = ItemKind.objects.get(name="Server")
        today = date.today()
        self.soon = Item.objects.create(
            name="Laptop lease", kind=self.server, warranty_end=today + timedelta(days=10)
        )
        self.later = Item.objects.create(
            name="Server rack", kind=self.server, warranty_end=today + timedelta(days=120)
        )
        self.expired = Item.objects.create(
            name="Old router", kind=self.server, warranty_end=today - timedelta(days=5)
        )

    def _fragment(self, query):
        response = self.client.get(reverse("items:item_list"), {"partial": "1", **query})
        return response.content.decode()

    def _shows(self, body, name):
        """Whether a card names this item."""
        return re.search(rf"<b>{re.escape(name)}</b>", body) is not None

    def test_warranty_chip_keeps_only_items_ending_within_90_days(self):
        body = self._fragment({"warranty": "1"})
        self.assertTrue(self._shows(body, "Laptop lease"))
        self.assertFalse(self._shows(body, "Server rack"))
        self.assertFalse(self._shows(body, "Old router"))

    def test_mine_and_unowned_chips(self):
        Item.objects.create(name="VPN gateway", kind=self.server, owner=self.agent)
        Item.objects.create(name="Backup NAS", kind=self.server, owner=self.colleague)

        mine = self._fragment({"mine": "1"})
        self.assertTrue(self._shows(mine, "VPN gateway"))
        self.assertFalse(self._shows(mine, "Backup NAS"))
        self.assertFalse(self._shows(mine, "Laptop lease"))

        unowned = self._fragment({"unowned": "1"})
        self.assertTrue(self._shows(unowned, "Laptop lease"))
        self.assertFalse(self._shows(unowned, "Backup NAS"))


class OpenTicketsChipTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria")
        self.client.force_login(self.agent)
        self.server = ItemKind.objects.get(name="Server")
        self.a = Item.objects.create(name="Mail server", kind=self.server)
        self.b = Item.objects.create(name="VPN gateway", kind=self.server)
        self.c = Item.objects.create(name="Backup NAS", kind=self.server)

    def _ticket(self, title, status):
        return Ticket.objects.create(
            title=title, description="body", created_by=self.agent, status=status
        )

    def test_open_tickets_chip_uses_links_in_both_directions(self):
        add_link(
            self.agent,
            ("item", str(self.a.pk)),
            ("ticket", str(self._ticket("Mail is down", "open").pk)),
            "affects",
        )
        add_link(
            self.agent,
            ("ticket", str(self._ticket("VPN flaps", "in_progress").pk)),
            ("item", str(self.b.pk)),
            "relates_to",
        )
        add_link(
            self.agent,
            ("item", str(self.c.pk)),
            ("ticket", str(self._ticket("NAS moved", "closed").pk)),
            "affects",
        )

        body = self.client.get(
            reverse("items:item_list"), {"partial": "1", "open_tickets": "1"}
        ).content.decode()
        self.assertIn("Mail server", body)
        self.assertIn("VPN gateway", body)
        self.assertNotIn("Backup NAS", body)


class DeviceKindTests(TestCase):
    def test_device_fields_seeded_for_server_and_network_kinds(self):
        server = ItemKind.objects.get(slug="server")
        self.assertTrue(server.is_device_like)
        self.assertEqual(server.vigil_device_type, "server")

        network = ItemKind.objects.get(slug="network-device")
        self.assertTrue(network.is_device_like)
        self.assertEqual(network.vigil_device_type, "switch")

        licence = ItemKind.objects.get(slug="licence")
        self.assertFalse(licence.is_device_like)
        self.assertEqual(licence.vigil_device_type, "")

    def test_kind_form_saves_device_fields(self):
        admin = User.objects.create_user("coral", "c@x.com", "pw", role="admin")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("items:kind_list"),
            {
                "name": "Access switch",
                "icon_color": "peach",
                "is_device_like": "on",
                "vigil_device_type": "switch",
            },
        )
        self.assertEqual(response.status_code, 302)
        kind = ItemKind.objects.get(name="Access switch")
        self.assertTrue(kind.is_device_like)
        self.assertEqual(kind.vigil_device_type, "switch")

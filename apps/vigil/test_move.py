"""Moving device-like Dynamic Items into Vigil (M17 phase 02)."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.items.models import Item, ItemKind
from apps.links.models import DynamicLink
from apps.tickets.models import Ticket
from apps.vigil import client as vigil_client
from apps.vigil import move
from apps.vigil.client import VigilUnavailable


class FakeVigil:
    """Records creates; can fail on chosen create calls and match names."""

    base_url = "https://vigil.example.gov"

    def __init__(self, fail_on=(), matches=None):
        self.fail_on = set(fail_on)
        self.matches = matches or {}
        self.creates: list[str] = []
        self.calls = 0

    def search(self, q, type=None):
        hit = self.matches.get((q, type))
        return [hit] if hit else []

    def create_device(self, payload):
        self.calls += 1
        if self.calls in self.fail_on:
            raise VigilUnavailable("Vigil did not answer in time.")
        self.creates.append(payload["name"])
        return {"id": f"dev-{payload['name']}", "label": payload["name"]}

    def resolve(self, type, ids):
        return {}


class MoveTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user("boss", "b@x.com", "pw", role="admin")
        self.server = ItemKind.objects.get(name="Server")
        self.ticket = Ticket.objects.create(
            title="Printer down", description="x", created_by=self.admin
        )

    def item(self, name):
        return Item.objects.create(name=name, kind=self.server)

    def link(self, item, item_is_source=True):
        if item_is_source:
            return DynamicLink.objects.create(
                source_type="item",
                source_id=str(item.pk),
                target_type="ticket",
                target_id=str(self.ticket.pk),
            )
        return DynamicLink.objects.create(
            source_type="ticket",
            source_id=str(self.ticket.pk),
            target_type="item",
            target_id=str(item.pk),
        )

    def run_move(self, fake):
        with patch.object(move, "get_client", return_value=fake):
            return move.move_all(self.admin)

    def test_move_rewrites_links_both_directions_then_deletes(self):
        printer = self.item("Printer")
        self.link(printer, item_is_source=True)
        self.link(printer, item_is_source=False)
        results = self.run_move(FakeVigil())
        self.assertEqual(results, [("Printer", "moved", "vigil:device:dev-Printer")])
        self.assertFalse(Item.objects.exists())
        self.assertEqual(
            set(DynamicLink.objects.values_list("source_type", "target_type")),
            {("vigil:device", "ticket"), ("ticket", "vigil:device")},
        )

    def test_move_uses_an_exact_name_match_instead_of_creating(self):
        self.item("web-01")
        fake = FakeVigil(matches={("web-01", "host"): {"id": "h1", "label": "web-01"}})
        results = self.run_move(fake)
        self.assertEqual(results[0][2], "vigil:host:h1")
        self.assertEqual(fake.creates, [])

    def test_move_failing_half_way_keeps_the_rest_and_reruns_cleanly(self):
        """Review Focus 4: Vigil fails on the third of five creates."""
        items = [self.item(f"Box {n}") for n in range(1, 6)]
        for each in items:
            self.link(each)
        fake = FakeVigil(fail_on={3})
        first = self.run_move(fake)

        self.assertEqual(
            [status for _, status, _ in first], ["moved", "moved", "failed", "moved", "moved"]
        )
        self.assertEqual(list(Item.objects.values_list("name", flat=True)), ["Box 3"])
        self.assertEqual(DynamicLink.objects.filter(source_type="item").count(), 1)
        self.assertEqual(DynamicLink.objects.filter(source_type="vigil:device").count(), 4)

        second = self.run_move(fake)
        self.assertEqual(second, [("Box 3", "moved", "vigil:device:dev-Box 3")])
        self.assertFalse(Item.objects.exists())
        self.assertEqual(
            sorted(fake.creates), [f"Box {n}" for n in range(1, 6)], "one create per item"
        )

    def test_rerun_after_create_but_before_delete_does_not_create_again(self):
        leftover = self.item("Switch")
        leftover.vigil_device_id = "dev-earlier"
        leftover.save()
        fake = FakeVigil()
        results = self.run_move(fake)
        self.assertEqual(results, [("Switch", "moved", "vigil:device:dev-earlier")])
        self.assertEqual(fake.creates, [])

    def test_a_link_that_would_duplicate_is_dropped_not_duplicated(self):
        printer = self.item("Printer")
        self.link(printer)
        DynamicLink.objects.create(
            source_type="vigil:device",
            source_id="dev-Printer",
            target_type="ticket",
            target_id=str(self.ticket.pk),
        )
        self.run_move(FakeVigil())
        self.assertEqual(DynamicLink.objects.count(), 1)

    def test_not_connected_moves_nothing(self):
        self.item("Printer")
        results = self.run_move(None)
        self.assertEqual(results, [("Printer", "failed", "Vigil is not connected.")])
        self.assertTrue(Item.objects.exists())


class MoveViewTests(TestCase):
    def test_move_view_is_admin_only(self):
        url = reverse("console:vigil_move_devices")
        for role in ("agent", "customer"):
            user = User.objects.create_user(f"u-{role}", f"{role}@x.com", "pw", role=role)
            self.client.force_login(user)
            response = self.client.post(url)
            self.assertIn(response.status_code, (302, 403), role)
            self.assertNotEqual(response.status_code, 200, role)

    def test_settings_explain_what_to_tick_without_device_write(self):
        admin = User.objects.create_user("boss2", "b2@x.com", "pw", role="admin")
        Item.objects.create(name="Printer", kind=ItemKind.objects.get(name="Server"))
        self.client.force_login(admin)
        with patch.object(vigil_client, "get_client", return_value=None):
            response = self.client.get(reverse("console:vigil_settings"))
        self.assertContains(response, "Can change devices")

"""The Vigil tabs on the Dynamic Items list: Hosts and Devices, live from Vigil.

``apps.vigil.client.get_client`` is the one connection check behind them; a
test hands the tabs a fake client by patching it there, exactly as the running
app sees a configured connection.
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.items import views as items_views
from apps.vigil import client as vigil_client
from apps.vigil.client import VigilUnavailable

NEW_VIGIL = {"version": "2026.16.0", "capabilities": ["devices", "host_facts"]}
OLDER_VIGIL = {"version": "2026.14.2", "ok": True}

HOST_ROW = {
    "type": "host",
    "id": "42",
    "label": "web-01.example.gov",
    "sub": "10.20.4.11",
    "status": "Online",
    "tone": "ok",
    "url": "https://vigil.example.gov/#open/host/42",
}

DEVICE_ROW = {
    "type": "device",
    "id": "7",
    "label": "switch-04",
    "sub": "10.20.9.4",
    "status": "Online",
    "tone": "bad",
    "url": "https://vigil.example.gov/#open/device/7",
}

SCRIPT_ROW = {
    "type": "host",
    "id": "43",
    "label": "sneaky",
    "sub": "",
    "status": "",
    "tone": "",
    "url": "javascript:alert(1)",
}


class CompositePatch:
    """Two patches used as one ``with`` block."""

    def __init__(self, *patches):
        self.patches = patches

    def __enter__(self):
        for patcher in self.patches:
            patcher.__enter__()
        return self

    def __exit__(self, *exc):
        for patcher in reversed(self.patches):
            patcher.__exit__(*exc)
        return False


class FakeVigilClient:
    """Answers ping and search, and records every search it was asked for."""

    def __init__(self, answer=None, results=None, error=None):
        self.answer = answer if answer is not None else {}
        self.results = results if results is not None else []
        self.error = error
        self.search_calls = []

    def capabilities(self) -> set[str]:
        listed = self.answer.get("capabilities")
        return {str(item) for item in listed} if isinstance(listed, list) else set()

    def search(self, q, type=None):
        self.search_calls.append((q, type))
        if self.error is not None:
            raise self.error
        return list(self.results)


class VigilTabTests(TestCase):
    def setUp(self):
        cache.clear()
        self.agent = User.objects.create_user("aria", "aria@x.com", "pw", role="agent")
        self.client.force_login(self.agent)
        self.url = reverse("items:item_list")

    def get(self, query=""):
        return self.client.get(f"{self.url}{query}")

    def connected(self, fake):
        """Both lookups the list uses, so one fake answers them alike."""
        return CompositePatch(
            patch.object(vigil_client, "get_client", return_value=fake),
            patch.object(items_views, "get_client", return_value=fake),
        )

    def test_device_tab_only_with_the_capability(self):
        with self.connected(FakeVigilClient(answer=OLDER_VIGIL)):
            self.assertNotIn("vigil-device", self.get().content.decode())

        cache.clear()
        with self.connected(FakeVigilClient(answer=NEW_VIGIL)):
            body = self.get().content.decode()

        self.assertIn("vigil-device", body)
        self.assertIn("Devices", body)

    def test_hosts_tab_searches_vigil(self):
        fake = FakeVigilClient(answer=NEW_VIGIL, results=[HOST_ROW])
        with self.connected(fake):
            response = self.get("?kind=vigil-host&q=web&partial=1")

        self.assertContains(response, "web-01.example.gov")
        self.assertContains(response, "from Vigil")
        self.assertIn(("web", "host"), fake.search_calls)

    def test_devices_tab_lists_vigil_devices(self):
        fake = FakeVigilClient(answer=NEW_VIGIL, results=[DEVICE_ROW])
        with self.connected(fake):
            response = self.get("?kind=vigil-device&q=switch&partial=1")

        self.assertContains(response, "switch-04")
        self.assertIn(("switch", "device"), fake.search_calls)

    def test_hosts_tab_without_query_shows_the_hint(self):
        fake = FakeVigilClient(answer=NEW_VIGIL, results=[HOST_ROW])
        with self.connected(fake):
            response = self.get("?kind=vigil-host&partial=1")

        self.assertContains(response, "Type to find hosts in Vigil")
        self.assertEqual(fake.search_calls, [])

    def test_devices_tab_without_the_capability_never_asks_vigil(self):
        fake = FakeVigilClient(answer=OLDER_VIGIL, results=[DEVICE_ROW])
        with self.connected(fake):
            response = self.get("?kind=vigil-device&q=switch&partial=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.search_calls, [])

    def test_vigil_down_shows_unavailable_and_still_200(self):
        fake = FakeVigilClient(
            answer=NEW_VIGIL, error=VigilUnavailable("Can't reach Vigil at vigil.example.gov.")
        )
        with self.connected(fake):
            response = self.get("?kind=vigil-host&q=web&partial=1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vigil unavailable")

    def test_no_vigil_no_vigil_tabs(self):
        with self.connected(None):
            body = self.get().content.decode()

        self.assertNotIn("vigil-host", body)
        self.assertNotIn("vigil-device", body)

    def test_jackil_items_are_not_on_the_vigil_tabs(self):
        with self.connected(FakeVigilClient(answer=NEW_VIGIL)):
            response = self.get("?kind=vigil-host&partial=1")

        body = response.content.decode()
        self.assertNotIn("item-card-icon", body)
        self.assertNotIn("filter-chip", body)

    def test_non_http_url_is_not_linked(self):
        fake = FakeVigilClient(answer=NEW_VIGIL, results=[SCRIPT_ROW])
        with self.connected(fake):
            response = self.get("?kind=vigil-host&q=sneaky&partial=1")

        body = response.content.decode()
        self.assertContains(response, "sneaky")
        self.assertNotIn("javascript:alert(1)", body)
        self.assertNotIn('href=""', body)

"""What a Vigil says it can do, and what an older one doesn't."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.accounts.models import User
from apps.links.registry import get_resolver
from apps.vigil import client as vigil_client
from apps.vigil import links as vigil_links
from apps.vigil.client import CAPABILITIES_KEY, VigilUnavailable, vigil_capabilities


class FakePingClient:
    """A client that answers ``ping()``, parsing capabilities as the real one does."""

    def __init__(self, answer=None, error=None):
        self.answer = answer if answer is not None else {}
        self.error = error
        self.ping_calls = 0

    def ping(self):
        self.ping_calls += 1
        if self.error is not None:
            raise self.error
        return self.answer

    def capabilities(self) -> set[str]:
        return vigil_client.VigilClient.capabilities(self)


class FakeRecordingClient(FakePingClient):
    """Every call is recorded, so a test can prove Vigil was never asked."""

    def __init__(self, answer=None, results=None, items=None, host=None):
        super().__init__(answer=answer)
        self.results = results if results is not None else []
        self.items = items if items is not None else {}
        self.host = host
        self.calls = []

    def search(self, q, type=None):
        self.calls.append(("search", q, type))
        return list(self.results)

    def resolve(self, type, ids):
        self.calls.append(("resolve", type, list(ids)))
        return {i: self.items[i] for i in ids if i in self.items}

    def detail(self, type, id):
        self.calls.append(("detail", type, id))
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

DEVICE_ITEM = {
    "type": "device",
    "id": "7",
    "label": "switch-04",
    "sub": "10.20.9.4",
    "status": "Online",
    "tone": "ok",
    "url": "https://vigil.example.gov/#open/device/7",
}

NEW_VIGIL = {"version": "2026.16.0", "capabilities": ["devices", "host_facts"]}
OLDER_VIGIL = {"version": "2026.14.2", "ok": True}


class CapabilitiesTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_capabilities_from_ping_and_cached(self):
        fake = FakePingClient(NEW_VIGIL)
        with patch.object(vigil_client, "get_client", return_value=fake):
            self.assertEqual(vigil_capabilities(), {"devices", "host_facts"})
            self.assertEqual(vigil_capabilities(), {"devices", "host_facts"})

        self.assertEqual(fake.ping_calls, 1, "the second call comes from the cache")
        self.assertEqual(cache.get(CAPABILITIES_KEY), ["devices", "host_facts"])

    def test_older_vigil_has_no_capabilities(self):
        fake = FakePingClient(OLDER_VIGIL)
        with patch.object(vigil_client, "get_client", return_value=fake):
            self.assertEqual(vigil_capabilities(), set())

    def test_unavailable_vigil_gives_no_capabilities_and_is_not_cached(self):
        fake = FakePingClient(error=VigilUnavailable("Can't reach Vigil at vigil.example.gov."))
        with patch.object(vigil_client, "get_client", return_value=fake):
            self.assertEqual(vigil_capabilities(), set())
            self.assertEqual(vigil_capabilities(), set())

        self.assertEqual(fake.ping_calls, 2, "a down Vigil is not cached")
        self.assertIsNone(cache.get(CAPABILITIES_KEY))

    def test_no_connection_gives_no_capabilities(self):
        with patch.object(vigil_client, "get_client", return_value=None):
            self.assertEqual(vigil_capabilities(), set())


class OlderVigilDeviceTests(TestCase):
    """Review Focus 5: a Vigil without the capability is never asked for devices."""

    def setUp(self):
        cache.clear()
        self.agent = User.objects.create_user("aria", "aria@x.com", "pw", role="agent")

    def _connected(self, fake):
        """Both modules see the one fake, the way the running app does."""
        return (
            patch.object(vigil_client, "get_client", return_value=fake),
            patch.object(vigil_links, "get_client", return_value=fake),
        )

    def test_older_vigil_never_sees_type_device(self):
        fake = FakeRecordingClient(answer=OLDER_VIGIL, items={"42": HOST_ITEM}, host=HOST_ITEM)
        client_patch, links_patch = self._connected(fake)
        with client_patch, links_patch:
            self.assertFalse(get_resolver("vigil:device").listed(self.agent))
            self.assertEqual(get_resolver("vigil:device").search("web", self.agent, 5), [])
            self.assertEqual(get_resolver("vigil:device").resolve(["42"], self.agent), {})
            self.assertIsNone(get_resolver("vigil:device").preview("42", self.agent))

            self.assertTrue(get_resolver("vigil:host").listed(self.agent))
            self.assertEqual(
                get_resolver("vigil:host").resolve(["42"], self.agent)["42"].label,
                "mail-01",
            )
            self.assertEqual(get_resolver("vigil:host").preview("42", self.agent).label, "mail-01")

        self.assertNotIn("device", [str(call) for call in fake.calls])

    def test_device_type_works_once_the_capability_is_there(self):
        fake = FakeRecordingClient(
            answer=NEW_VIGIL,
            results=[DEVICE_ITEM],
            items={"7": DEVICE_ITEM},
            host=DEVICE_ITEM,
        )
        client_patch, links_patch = self._connected(fake)
        with client_patch, links_patch:
            self.assertTrue(get_resolver("vigil:device").listed(self.agent))
            self.assertEqual(
                [t.label for t in get_resolver("vigil:device").search("switch", self.agent, 5)],
                ["switch-04"],
            )
            self.assertEqual(
                get_resolver("vigil:device").resolve(["7"], self.agent)["7"].label, "switch-04"
            )
            self.assertEqual(
                get_resolver("vigil:device").preview("7", self.agent).label, "switch-04"
            )

        self.assertIn(("search", "switch", None), fake.calls)
        self.assertIn(("resolve", "device", ["7"]), fake.calls)
        self.assertIn(("detail", "device", "7"), fake.calls)

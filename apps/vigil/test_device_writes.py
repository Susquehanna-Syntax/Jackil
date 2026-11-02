"""Creating devices in Vigil: the client's writes, and what a new item sends."""

import urllib.error
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import Department, User
from apps.items.models import Item, ItemKind
from apps.vigil import client as vigil_client
from apps.vigil.client import (
    VigilClient,
    VigilRefused,
    VigilRejected,
    VigilUnavailable,
)
from apps.vigil.devices import can_write_devices, device_payload


class FakeBody:
    """The readable part of an HTTPError."""

    def __init__(self, body=""):
        self.body = body.encode() if isinstance(body, str) else body

    def read(self, _limit=-1):
        return self.body


class FakeResponse(FakeBody):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Recorder:
    """Stand-in for ``urlopen`` that records each write and answers in turn.

    Header names are kept as they come out of ``Request.header_items``, which
    spells the content type "Content-type" however we hand it over.
    """

    def __init__(self, *results):
        self.results = list(results)
        #: Each call: url, method, header **names** lower-cased, body text.
        self.requests: list[tuple[str, str, dict[str, str], str | None]] = []

    def __call__(self, request, timeout=None):
        headers = {name.lower(): value for name, value in request.header_items()}
        self.requests.append(
            (
                request.full_url,
                request.method,
                headers,
                request.data.decode() if request.data else None,
            )
        )
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)

    @property
    def calls(self):
        return self.requests


def http_error(code, body="", reason="Bad Request"):
    error = urllib.error.HTTPError("https://vigil.example.gov", code, reason, {}, FakeBody(body))
    error.close = lambda: None
    return error


CREATED = '{"type": "device", "id": "7", "label": "switch-04", "facts": []}'


class ClientWriteTests(SimpleTestCase):
    def make(self):
        return VigilClient("https://vigil.example.gov", "vjk_test")

    def test_create_device_posts_json_and_returns_the_item(self):
        recorder = Recorder(CREATED)
        with patch.object(vigil_client, "urlopen", recorder):
            device = self.make().create_device({"name": "switch-04", "device_type": "switch"})

        url, method, headers, body = recorder.calls[0]
        self.assertEqual(url, "https://vigil.example.gov/api/v1/jackil/integration/devices/")
        self.assertEqual(method, "POST")
        self.assertEqual(headers.get("content-type"), "application/json")
        self.assertEqual(headers.get("authorization"), "Bearer vjk_test")
        self.assertIn('"device_type": "switch"', body)
        self.assertEqual(device["id"], "7")

    def test_write_403_raises_refused(self):
        with patch.object(vigil_client, "urlopen", Recorder(http_error(403, ""))):
            with self.assertRaises(VigilRefused) as caught:
                self.make().create_device({"name": "x"})

        self.assertEqual(str(caught.exception), "Vigil does not let this key change devices.")
        self.assertTrue(isinstance(caught.exception, VigilUnavailable))

    def test_write_400_carries_field_errors(self):
        refused = http_error(400, '{"device_type": ["Not a valid choice."]}')
        with patch.object(vigil_client, "urlopen", Recorder(refused)):
            with self.assertRaises(VigilRejected) as caught:
                self.make().update_device("7", {"device_type": "toaster"})

        self.assertEqual(caught.exception.errors, {"device_type": ["Not a valid choice."]})
        self.assertIn("Not a valid choice.", str(caught.exception))

    def test_delete_204_returns_none(self):
        recorder = Recorder("")
        with patch.object(vigil_client, "urlopen", recorder):
            self.assertIsNone(self.make().delete_device("7"))

        url, method, _headers, body = recorder.calls[0]
        self.assertEqual(method, "DELETE")
        self.assertIsNone(body)
        self.assertEqual(url, "https://vigil.example.gov/api/v1/jackil/integration/devices/7/")

    def test_delete_of_a_device_that_is_gone_is_nothing_to_do(self):
        with patch.object(vigil_client, "urlopen", Recorder(http_error(404, "", "Not Found"))):
            self.assertIsNone(self.make().delete_device("7"))


class DevicePayloadTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            "aria", "aria@example.gov", "pw", role="admin", first_name="Aria", last_name="Bloom"
        )
        self.kind = ItemKind.objects.get(name="Network device")
        self.department = Department.objects.create(name="Facilities")

    def item(self, **overrides):
        fields = {
            "name": "switch-04",
            "kind": self.kind,
            "owner": self.owner,
            "department": self.department,
            "vendor": "Acme",
            "notes": "core uplink",
            "attributes": {"Serial": "X1", "IP": "10.20.9.4"},
        }
        fields.update(overrides)
        return Item(**fields)

    def test_device_payload_maps_owner_serial_department_and_extra(self):
        from datetime import date

        payload = device_payload(self.item(warranty_end=date(2028, 6, 30)))

        self.assertEqual(payload["name"], "switch-04")
        self.assertEqual(payload["device_type"], "switch")
        self.assertEqual(payload["vendor"], "Acme")
        self.assertEqual(payload["warranty_end"], "2028-06-30")
        self.assertEqual(payload["owner"], "Aria Bloom <aria@example.gov>")
        self.assertEqual(payload["serial"], "X1")
        self.assertEqual(payload["notes"], "core uplink")
        self.assertEqual(payload["extra"], {"IP": "10.20.9.4", "Department": "Facilities"})

    def test_an_item_with_nothing_of_its_own_still_gives_vigil_a_whole_record(self):
        kind = ItemKind.objects.create(name="Mystery box")
        payload = device_payload(
            self.item(kind=kind, owner=None, department=None, attributes={}, vendor="", notes="")
        )

        self.assertEqual(payload["device_type"], "other")
        self.assertIsNone(payload["warranty_end"])
        self.assertEqual(payload["owner"], "")
        self.assertEqual(payload["serial"], "")
        self.assertEqual(payload["extra"], {})

    def test_a_owner_with_no_address_is_just_a_name(self):
        owner = User.objects.create_user("coral", "", "pw", role="agent")
        payload = device_payload(self.item(owner=owner))

        self.assertEqual(payload["owner"], "coral")

    def test_extra_is_trimmed_to_what_vigil_will_take(self):
        attributes = {f"Fact {n}": "x" * 400 for n in range(60)}
        payload = device_payload(self.item(attributes=attributes))

        self.assertEqual(len(payload["extra"]), 50)
        self.assertEqual(len(next(iter(payload["extra"].values()))), 300)


class FakeVigil(VigilClient):
    """A client whose writes the tests steer, recording what it was sent.

    Reading through ``_get`` keeps the real ``capabilities()`` — and the
    five-minute cache around it — in play, rather than a stand-in that agrees
    with them by luck.
    """

    def __init__(self, capabilities=(), error=None, created_id="7"):
        super().__init__("https://vigil.example.gov", "vjk_test")
        self.answer = {"ok": True, "capabilities": sorted(capabilities)}
        self.error = error
        self.created_id = created_id
        self.created: list[dict] = []

    def _get(self, path):
        return dict(self.answer)

    def create_device(self, payload):
        self.created.append(payload)
        if isinstance(self.error, Exception):
            raise self.error
        return {"id": self.created_id, "label": payload["name"]}


class NewItemTests(TestCase):
    """A device-like Dynamic Item is created in Vigil, and Jackil keeps no row."""

    def setUp(self):
        cache.clear()
        self.agent = User.objects.create_user("aria", "aria@x.com", "pw", role="agent")
        self.client.force_login(self.agent)
        self.server = ItemKind.objects.get(name="Server")
        self.service = ItemKind.objects.get(name="Service")

    def payload(self, **overrides):
        fields = {
            "name": "File server",
            "kind": self.server.pk,
            "owner": "",
            "department": "",
            "vendor": "Globex",
            "warranty_end": "",
            "notes": "",
            "vigil_host_id": "",
            "attributes_text": "Serial: X1",
        }
        fields.update(overrides)
        return fields

    def connected(self, fake):
        return patch.object(vigil_client, "get_client", return_value=fake)

    def create(self, **overrides):
        return self.client.post(reverse("items:item_create"), self.payload(**overrides))

    def test_new_device_like_item_goes_to_vigil_and_jackil_keeps_no_row(self):
        fake = FakeVigil(capabilities={"device_write"})
        with self.connected(fake):
            response = self.create()

        self.assertEqual(response.status_code, 302)
        self.assertIn("?kind=vigil-device", response.url)
        self.assertEqual(Item.objects.count(), 0, "Jackil kept nothing")
        self.assertEqual([sent["name"] for sent in fake.created], ["File server"])
        self.assertEqual(fake.created[0]["device_type"], "server")
        self.assertEqual(fake.created[0]["serial"], "X1")

    def test_without_device_write_the_item_stays_in_jackil(self):
        fake = FakeVigil()
        with self.connected(fake):
            response = self.create()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Item.objects.count(), 1)
        self.assertEqual(fake.created, [], "Vigil was never asked to take it")

    def test_a_kind_that_is_not_device_like_stays_in_jackil_even_with_the_key(self):
        fake = FakeVigil(capabilities={"device_write"})
        with self.connected(fake):
            self.create(kind=self.service.pk)

        self.assertEqual(Item.objects.count(), 1)
        self.assertEqual(fake.created, [])

    def test_vigil_rejecting_the_device_saves_nothing_and_shows_why(self):
        fake = FakeVigil(
            capabilities={"device_write"},
            error=VigilRejected(
                "Vigil did not accept the device: bad type.",
                {"device_type": ["Not a valid choice."]},
            ),
        )
        with self.connected(fake):
            response = self.create()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Not a valid choice.")
        self.assertEqual(Item.objects.count(), 0)
        stored = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertEqual(
            stored,
            [
                "Vigil could not take it right now: Vigil did not accept the device: bad type.. "
                "Nothing was saved."
            ],
        )

    def test_vigil_being_down_says_so_and_saves_nothing(self):
        fake = FakeVigil(
            capabilities={"device_write"},
            error=VigilUnavailable("Can't reach Vigil at vigil.example.gov."),
        )
        with self.connected(fake):
            response = self.create()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Item.objects.count(), 0)
        stored = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertEqual(
            stored,
            [
                "Vigil could not take it right now: Can't reach Vigil at "
                "vigil.example.gov.. Nothing was saved."
            ],
        )

    def test_the_form_says_device_kinds_are_kept_in_vigil(self):
        fake = FakeVigil(capabilities={"device_write"})
        with self.connected(fake):
            page = self.client.get(reverse("items:item_create"))

        self.assertContains(page, "Device kinds are kept in Vigil.")

    def test_the_note_is_absent_while_vigil_cannot_take_devices(self):
        with self.connected(FakeVigil()):
            page = self.client.get(reverse("items:item_create"))

        self.assertNotIn("Device kinds are kept in Vigil.", page.content.decode())

    def test_can_write_devices_needs_both_the_connection_and_the_capability(self):
        self.assertFalse(can_write_devices())
        with self.connected(FakeVigil(capabilities={"device_write"})):
            self.assertTrue(can_write_devices())

"""The Vigil connection model and read-only client."""

import ssl
import urllib.error
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import User
from apps.vigil import client
from apps.vigil.client import VigilClient, VigilUnavailable, get_client
from apps.vigil.models import VigilConnection


class FakeBody:
    """The readable part of an HTTPError; also closes so urllib can let go."""

    def __init__(self, body=""):
        self.body = body.encode() if isinstance(body, str) else body

    def read(self, _limit=-1):
        return self.body

    def close(self):
        pass


class FakeResponse(FakeBody):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Recorder:
    """Stand-in for urllib.request.urlopen that never touches the network."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append((request.full_url, dict(request.header_items()), timeout))
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)

    @property
    def urls(self):
        return [call[0] for call in self.calls]


def make_client():
    return VigilClient("https://vigil.example.gov", "vjk_test")


class ConnectionModelTests(TestCase):
    def test_key_is_encrypted_at_rest_and_round_trips(self):
        connection = VigilConnection.get_solo()
        connection.set_key("vjk_abc123")
        connection.save()

        self.assertTrue(connection.key_encrypted)
        self.assertNotIn("vjk_abc123", connection.key_encrypted)

        reloaded = VigilConnection.objects.get(pk=1)
        self.assertEqual(reloaded.get_key(), "vjk_abc123")

    def test_set_key_to_blank_clears_a_saved_key(self):
        connection = VigilConnection.get_solo()
        connection.set_key("vjk_abc123")
        connection.set_key("")

        self.assertEqual(connection.key_encrypted, "")
        self.assertEqual(connection.get_key(), "")

    def test_get_key_is_blank_when_the_ciphertext_cannot_be_read(self):
        connection = VigilConnection.get_solo()
        connection.key_encrypted = "not-a-fernet-token"

        self.assertEqual(connection.get_key(), "")

    def test_get_client_is_none_until_configured(self):
        self.assertIsNone(get_client())

        connection = VigilConnection.get_solo()
        connection.base_url = "https://vigil.example.gov/"
        connection.enabled = True
        connection.save()
        self.assertIsNone(get_client())

        connection.set_key("vjk_abc123")
        connection.save()
        resolved = get_client()
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.base_url, "https://vigil.example.gov")

    def test_is_configured_needs_the_flag_the_address_and_a_key(self):
        connection = VigilConnection.get_solo()
        self.assertFalse(connection.is_configured)

        connection.enabled = True
        connection.base_url = "https://vigil.example.gov"
        self.assertFalse(connection.is_configured)

        connection.set_key("vjk_abc123")
        self.assertTrue(connection.is_configured)

        connection.enabled = False
        self.assertFalse(connection.is_configured)


class ClientTests(SimpleTestCase):
    def test_ping_sends_the_bearer_key_and_parses_json(self):
        recorder = Recorder('{"ok": true, "version": "2026.16.0", "acting_as": "alice"}')
        with patch.object(client, "urlopen", recorder):
            answer = make_client().ping()

        self.assertEqual(answer["version"], "2026.16.0")
        self.assertEqual(answer["acting_as"], "alice")
        url, headers, timeout = recorder.calls[0]
        self.assertEqual(url, "https://vigil.example.gov/api/v1/jackil/integration/ping/")
        self.assertEqual(headers.get("Authorization"), "Bearer vjk_test")
        self.assertEqual(headers.get("Accept"), "application/json")
        self.assertEqual(timeout, client.TIMEOUT)

    def test_timeout_tls_unreachable_and_bad_json_become_plain_messages(self):
        cases = [
            (TimeoutError(), "Vigil did not answer in time."),
            (urllib.error.URLError(TimeoutError()), "Vigil did not answer in time."),
            (ssl.SSLError("bad cert"), "Vigil's certificate was not accepted."),
            (
                urllib.error.URLError(ssl.SSLError("bad cert")),
                "Vigil's certificate was not accepted.",
            ),
            (OSError("no route"), "Can't reach Vigil at vigil.example.gov."),
            ("not json at all", "Vigil sent an answer Jackil could not read."),
        ]
        for result, expected in cases:
            with self.subTest(failure=expected):
                with patch.object(client, "urlopen", Recorder(result)):
                    with self.assertRaises(VigilUnavailable) as caught:
                        make_client().ping()
                self.assertEqual(str(caught.exception), expected)

    def test_401_says_the_key_was_refused_and_404_on_ping_says_update_vigil(self):
        refused = urllib.error.HTTPError(
            "https://vigil.example.gov", 401, "Unauthorized", {}, FakeBody()
        )
        with patch.object(client, "urlopen", Recorder(refused)):
            with self.assertRaises(VigilUnavailable) as caught:
                make_client().ping()
        self.assertEqual(str(caught.exception), "Vigil refused the integration key.")

        forbidden = urllib.error.HTTPError(
            "https://vigil.example.gov", 403, "Forbidden", {}, FakeBody()
        )
        with patch.object(client, "urlopen", Recorder(forbidden)):
            with self.assertRaises(VigilUnavailable) as caught:
                make_client().ping()
        self.assertEqual(str(caught.exception), "Vigil refused the integration key.")

        missing = urllib.error.HTTPError(
            "https://vigil.example.gov", 404, "Not Found", {}, FakeBody()
        )
        with patch.object(client, "urlopen", Recorder(missing)):
            with self.assertRaises(VigilUnavailable) as caught:
                make_client().ping()
        self.assertEqual(
            str(caught.exception),
            "Vigil does not have the Jackil integration. Update Vigil to 2026.16 or later.",
        )

    def test_400_quotes_the_error_from_the_body_and_other_codes_the_number(self):
        bad_request = urllib.error.HTTPError(
            "https://vigil.example.gov",
            400,
            "Bad Request",
            {},
            FakeResponse('{"error": "Unknown type"}'),
        )
        with patch.object(client, "urlopen", Recorder(bad_request)):
            with self.assertRaises(VigilUnavailable) as caught:
                make_client().search("web")
        self.assertEqual(str(caught.exception), "Vigil did not accept the request: Unknown type.")

        unreadable_body = urllib.error.HTTPError(
            "https://vigil.example.gov", 400, "Bad Request", {}, FakeBody()
        )
        with patch.object(client, "urlopen", Recorder(unreadable_body)):
            with self.assertRaises(VigilUnavailable) as caught:
                make_client().search("web")
        self.assertEqual(str(caught.exception), "Vigil did not accept the request: Bad Request.")

        broken = urllib.error.HTTPError(
            "https://vigil.example.gov", 503, "Unavailable", {}, FakeBody()
        )
        with patch.object(client, "urlopen", Recorder(broken)):
            with self.assertRaises(VigilUnavailable) as caught:
                make_client().widgets()
        self.assertEqual(str(caught.exception), "Vigil had an error (503).")

    def test_detail_and_widget_return_none_on_404(self):
        missing = urllib.error.HTTPError(
            "https://vigil.example.gov", 404, "Not Found", {}, FakeBody()
        )
        with patch.object(client, "urlopen", Recorder(missing)):
            self.assertIsNone(make_client().detail("host", "42"))
            self.assertIsNone(make_client().widget("hosts-at-risk", {}))

    def test_detail_returns_the_item_and_widget_the_payload(self):
        item = '{"type": "host", "id": "42", "label": "web-01", "facts": []}'
        with patch.object(client, "urlopen", Recorder(item)):
            self.assertEqual(make_client().detail("host", "42")["label"], "web-01")

        widget = '{"version": 1, "shape": "stat", "data": {"value": 3}}'
        with patch.object(client, "urlopen", Recorder(widget)) as recorder:
            payload = make_client().widget("open-tickets", {"days": 7})
        self.assertEqual(payload["data"]["value"], 3)
        self.assertEqual(
            recorder.urls[0].split("?")[0].split("/integration/")[1], "widgets/open-tickets/"
        )
        self.assertIn("days=7", recorder.urls[0])

    def test_resolve_batches_over_100_ids_and_skips_empty(self):
        recorder = Recorder('{"items": {"1": {"id": "1"}}}')
        with patch.object(client, "urlopen", recorder):
            self.assertEqual(make_client().resolve("host", []), {})
            self.assertEqual(recorder.calls, [])

            ids = [str(n) for n in range(1, 201)]
            items = make_client().resolve("host", ids)

        self.assertEqual(items, {"1": {"id": "1"}})
        self.assertEqual(len(recorder.urls), 2)
        first, second = recorder.urls
        self.assertIn("type=host", first)
        self.assertTrue(first.endswith("%2C100"), first)
        self.assertTrue(second.endswith("%2C200"), second)

    def test_search_sends_the_query_and_returns_results(self):
        recorder = Recorder('{"results": [{"type": "host", "id": "1"}]}')
        with patch.object(client, "urlopen", recorder):
            results = make_client().search("web-01", type="host")

        self.assertEqual(results[0]["id"], "1")
        self.assertIn("q=web-01", recorder.urls[0])
        self.assertIn("type=host", recorder.urls[0])

    def test_search_below_two_chars_returns_nothing_without_a_request(self):
        recorder = Recorder('{"results": []}')
        with patch.object(client, "urlopen", recorder):
            self.assertEqual(make_client().search("w"), [])
            self.assertEqual(recorder.calls, [])

    def test_widgets_unwraps_the_list(self):
        with patch.object(
            client, "urlopen", Recorder('{"version": 1, "widgets": [{"kind": "k"}]}')
        ) as recorder:
            self.assertEqual(make_client().widgets()[0]["kind"], "k")
        self.assertTrue(recorder.urls[0].endswith("/integration/widgets/"))

    def test_unknown_type_raises_value_error_without_a_request(self):
        recorder = Recorder('{"items": {}}')
        with patch.object(client, "urlopen", recorder):
            for call in (
                lambda: make_client().resolve("widget", ["1"]),
                lambda: make_client().detail("widget", "1"),
                lambda: make_client().search("web-01", type="widget"),
            ):
                with self.subTest(call=call):
                    with self.assertRaises(ValueError):
                        call()
            self.assertEqual(recorder.calls, [])


class SettingsPageTests(TestCase):
    def setUp(self):
        self.url = "/settings/vigil/"
        self.admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")
        self.agent = User.objects.create_user("agt", "agt@x.com", "pass", role="agent")
        self.customer = User.objects.create_user("cust", "cust@x.com", "pass", role="customer")

    def test_settings_page_admin_only(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

        for user in (self.agent, self.customer):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 302)
                self.assertNotIn("/settings/vigil/", response.url)

        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vigil")
        self.assertContains(response, "Test connection")

    def messages_from(self, response):
        return [(m.level_tag, str(m)) for m in get_messages(response.wsgi_request)]

    def test_save_keeps_the_key_when_blank_and_rejects_a_non_vigil_key(self):
        self.client.force_login(self.admin)
        connection = VigilConnection.get_solo()
        connection.set_key("vjk_saved")
        connection.save()

        response = self.client.post(
            self.url,
            {
                "action": "save",
                "base_url": "https://vigil.example.gov/",
                "key": "",
                "enabled": "on",
            },
            follow=True,
        )
        self.assertIn(("success", "Vigil connection saved."), self.messages_from(response))

        connection.refresh_from_db()
        self.assertEqual(connection.base_url, "https://vigil.example.gov")
        self.assertTrue(connection.enabled)
        self.assertEqual(connection.get_key(), "vjk_saved")

        response = self.client.post(
            self.url,
            {
                "action": "save",
                "base_url": "https://vigil.example.gov",
                "key": "skope",
                "enabled": "on",
            },
            follow=True,
        )
        self.assertIn(
            (
                "error",
                "That is not a Vigil key for Jackil; an integration key starts "
                "with vjk_ and a scoped API key with vsk_.",
            ),
            self.messages_from(response),
        )
        connection.refresh_from_db()
        self.assertEqual(connection.get_key(), "vjk_saved")

    def test_save_needs_an_address_when_reading_is_switched_on(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"action": "save", "enabled": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(VigilConnection.get_solo().enabled)

    def test_test_connection_records_success_and_failure(self):
        self.client.force_login(self.admin)
        connection = VigilConnection.get_solo()
        connection.base_url = "https://vigil.example.gov"
        connection.enabled = True
        connection.save()

        response = self.client.post(self.url, {"action": "test"})
        self.assertEqual(response.status_code, 302)
        connection.refresh_from_db()
        self.assertIsNone(connection.last_checked_at)

        connection.set_key("vjk_saved")
        connection.save()

        refused = urllib.error.HTTPError(
            "https://vigil.example.gov", 401, "Unauthorized", {}, FakeBody()
        )
        with patch.object(client, "urlopen", Recorder(refused)):
            self.client.post(self.url, {"action": "test"})
        connection.refresh_from_db()
        self.assertFalse(connection.last_ok)
        self.assertEqual(connection.last_message, "Vigil refused the integration key.")
        self.assertIsNotNone(connection.last_checked_at)
        self.assertEqual(connection.vigil_version, "")

        with patch.object(
            client,
            "urlopen",
            Recorder('{"ok": true, "version": "2026.16.0", "acting_as": "alice"}'),
        ):
            self.client.post(self.url, {"action": "test"})
        connection.refresh_from_db()
        self.assertTrue(connection.last_ok)
        self.assertEqual(connection.last_message, "Connected to Vigil 2026.16.0 as alice.")
        self.assertEqual(connection.vigil_version, "2026.16.0")


class WidgetListNotFoundTests(TestCase):
    """The widget list is not a per-item path: its 404 means an old Vigil."""

    def test_widget_list_404_says_update_vigil(self):
        import urllib.error
        from unittest import mock

        from apps.vigil.client import VigilClient, VigilUnavailable

        def refuse(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

        with mock.patch("apps.vigil.client.urlopen", side_effect=refuse):
            with self.assertRaises(VigilUnavailable) as caught:
                VigilClient("https://vigil.example", "vjk_x").widgets()
        self.assertIn("Update Vigil", str(caught.exception))

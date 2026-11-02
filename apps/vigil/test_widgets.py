"""Vigil's widgets as dashboard widgets: catalog, data, and outage behaviour."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.vigil import widgets as vigil_widgets
from apps.vigil.client import VigilUnavailable
from apps.vigil.links import DOWN_KEY
from apps.vigil.widgets import remote_widget_data

STAT_ENTRY = {
    "kind": "stat",
    "title": "A single number",
    "description": "One number, live from Vigil.",
    "shape": "stat",
    "settings": {
        "metric": {
            "type": "choice",
            "label": "Metric",
            "default": "alerts_firing",
            "choices": [["alerts_firing", "Alerts firing"], ["hosts_total", "Hosts total"]],
        }
    },
}
ALERT_LIST_ENTRY = {
    "kind": "alert_list",
    "title": "Alert list",
    "description": "The alerts Vigil is firing.",
    "shape": "list",
    "settings": {"limit": {"type": "int", "label": "Rows", "default": 10, "min": 1, "max": 50}},
}
HOSTS_ENTRY = {
    "kind": "hosts_online",
    "title": "Hosts online",
    "description": "How many hosts answered the last probe.",
    "shape": "gauge",
    "settings": {},
}
CATALOG = [STAT_ENTRY, ALERT_LIST_ENTRY, HOSTS_ENTRY]


class FakeClient:
    def __init__(self, catalog=None, payload=None, failure=None):
        self.catalog = catalog if catalog is not None else CATALOG
        self.payload = payload
        self.failure = failure
        self.widgets_calls = 0
        self.widget_calls = []

    def widgets(self):
        self.widgets_calls += 1
        if self.failure == "catalog":
            raise VigilUnavailable("Can't reach Vigil at vigil:8000.")
        return self.catalog

    def widget(self, kind, params):
        self.widget_calls.append((kind, dict(params)))
        if isinstance(self.failure, Exception):
            raise self.failure
        return self.payload


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


def stat_payload():
    return {"version": 1, "shape": "stat", "data": {"value": 3, "label": "Alerts firing"}}


class VigilWidgetsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.agent = make_user("vig-agent", "agent")
        self.customer = make_user("vig-customer", "customer")
        self.client_obj = FakeClient()
        patcher = patch("apps.vigil.widgets.get_client", return_value=self.client_obj)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _login(self, user):
        self.api.force_authenticate(user)

    def test_catalog_lists_vigil_widgets_in_their_own_group(self):
        self._login(self.agent)
        body = self.api.get("/dashboards/api/catalog/").json()
        widgets = body["widgets"]
        stat = widgets["vigil:stat"]
        self.assertEqual(stat["group"], "vigil")
        self.assertEqual(stat["shape"], "stat")
        self.assertEqual(stat["label"], "A single number")
        metric = stat["settings"]["metric"]
        self.assertEqual(metric["type"], "choice")
        self.assertEqual(
            metric["options"], [["alerts_firing", "Alerts firing"], ["hosts_total", "Hosts total"]]
        )
        self.assertIn("title", stat["settings"])
        rows = widgets["vigil:alert_list"]["settings"]["limit"]
        self.assertEqual(rows["type"], "int")
        self.assertEqual((rows["min"], rows["max"], rows["default"]), (1, 50, 10))
        self.assertEqual(widgets["vigil:hosts_online"]["shape"], "gauge")
        self.assertIn("ticket_list", widgets)

    def test_catalog_has_no_vigil_group_when_not_connected_or_down(self):
        self._login(self.agent)
        with patch("apps.vigil.widgets.get_client", return_value=None):
            widgets = self.api.get("/dashboards/api/catalog/").json()["widgets"]
        self.assertFalse([k for k in widgets if k.startswith("vigil:")])

        down = FakeClient(catalog=CATALOG, failure="catalog")
        with patch("apps.vigil.widgets.get_client", return_value=down):
            widgets = self.api.get("/dashboards/api/catalog/").json()["widgets"]
        self.assertFalse([k for k in widgets if k.startswith("vigil:")])
        cache.set(DOWN_KEY, "Can't reach Vigil.", 30)
        widgets = self.api.get("/dashboards/api/catalog/").json()["widgets"]
        self.assertFalse([k for k in widgets if k.startswith("vigil:")])

    def test_catalog_is_cached(self):
        self._login(self.agent)
        self.api.get("/dashboards/api/catalog/")
        self.api.get("/dashboards/api/catalog/")
        self.assertEqual(self.client_obj.widgets_calls, 1)

    def test_remote_widget_data_passes_cleaned_settings(self):
        self.client_obj.payload = stat_payload()
        params = {"metric": "bogus", "limit": "999", "title": "my card"}
        entry_map = {
            "vigil:stat": {
                "settings": {
                    "metric": {
                        "type": "choice",
                        "label": "Metric",
                        "default": "alerts_firing",
                        "options": [["alerts_firing", "Alerts firing"]],
                    },
                    "limit": {
                        "type": "int",
                        "label": "Rows",
                        "default": 10,
                        "min": 1,
                        "max": 50,
                    },
                }
            }
        }
        with patch("apps.vigil.widgets.remote_catalog", return_value=entry_map):
            remote_widget_data("vigil:stat", params, self.agent)
        self.assertEqual(
            self.client_obj.widget_calls, [("stat", {"metric": "alerts_firing", "limit": 50})]
        )

    def test_remote_widget_data_says_unavailable_when_vigil_is_down_and_stops_calling(self):
        self.client_obj.failure = VigilUnavailable("Can't reach Vigil at vigil:8000.")
        envelope = remote_widget_data("vigil:stat", {}, self.agent)
        self.assertEqual(envelope["shape"], "stat")
        self.assertEqual(envelope["data"]["label"], "Vigil unavailable")
        self.assertEqual(envelope["data"]["tone"], "muted")
        self.assertIn(DOWN_KEY, cache)
        calls_before = len(self.client_obj.widget_calls)
        again = remote_widget_data("vigil:stat", {}, self.agent)
        self.assertEqual(again["data"]["label"], "Vigil unavailable")
        self.assertEqual(len(self.client_obj.widget_calls), calls_before)

    def test_unknown_remote_widget_says_it_no_longer_exists(self):
        self.client_obj.payload = None
        envelope = remote_widget_data("vigil:gone", {}, self.agent)
        self.assertEqual(envelope["shape"], "stat")
        self.assertEqual(envelope["data"]["label"], "This Vigil widget no longer exists.")

    def test_bad_remote_payload_becomes_a_message(self):
        for payload in (
            {"shape": "bubble", "data": {}},
            {"shape": "stat", "data": {"label": "no value"}},
            {"shape": "stat", "data": "not a dict"},
        ):
            with self.subTest(payload=payload):
                self.client_obj.payload = payload
                envelope = remote_widget_data("vigil:stat", {}, self.agent)
                self.assertEqual(envelope["shape"], "stat")
                self.assertEqual(
                    envelope["data"]["label"], "Vigil sent a widget Jackil could not draw."
                )

    def test_layout_keeps_a_vigil_tile_while_vigil_is_down(self):
        self._login(self.agent)
        board = self.api.post("/dashboards/api/", {"name": "Ops"}, format="json").json()
        cache.set(DOWN_KEY, "Can't reach Vigil.", 30)
        layout = {
            "widgets": [
                {"kind": "vigil:stat", "x": 0, "y": 0, "w": 6, "h": 4, "settings": {}},
                {"kind": "vigil:alert_list", "x": 6, "y": 0, "w": 1, "h": 1, "settings": {}},
            ]
        }
        response = self.api.put(f"/dashboards/api/{board['id']}/layout/", layout, format="json")
        self.assertEqual(response.status_code, 200)
        saved = response.json()["widgets"]
        self.assertEqual([w["kind"] for w in saved], ["vigil:stat", "vigil:alert_list"])
        self.assertEqual((saved[0]["w"], saved[0]["h"]), (6, 4))
        self.assertEqual((saved[1]["w"], saved[1]["h"]), (2, 2))

    def test_widget_data_endpoint_draws_a_vigil_widget(self):
        self._login(self.agent)
        self.client_obj.payload = stat_payload()
        body = self.api.get("/dashboards/api/widgets/vigil:stat/data/?metric=hosts_total").json()
        self.assertEqual(body["shape"], "stat")
        self.assertEqual(self.client_obj.widget_calls[-1][0], "stat")

    def test_customer_403_on_remote_widget_data(self):
        self._login(self.customer)
        response = self.api.get("/dashboards/api/widgets/vigil:stat/data/")
        self.assertEqual(response.status_code, 403)


class NoClientTests(TestCase):
    def setUp(self):
        cache.clear()
        self.agent = make_user("vig-agent2", "agent")

    def test_no_connection_is_a_stat_that_says_so(self):
        with patch("apps.vigil.widgets.get_client", return_value=None):
            envelope = remote_widget_data("vigil:stat", {}, self.agent)
        self.assertEqual(
            envelope,
            {
                "version": 1,
                "shape": "stat",
                "data": {"value": 0, "label": "Vigil is not connected.", "tone": "muted"},
            },
        )

    def test_is_remote_only_matches_namespaced_kinds(self):
        self.assertTrue(vigil_widgets.is_remote("vigil:hosts_online"))
        self.assertFalse(vigil_widgets.is_remote("ticket_list"))
        self.assertFalse(vigil_widgets.is_remote("vigil:Stat"))
        self.assertFalse(vigil_widgets.is_remote(None))

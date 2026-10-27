"""Dashboards — starter layout, ownership, layout replacement, settings hygiene."""

from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.dashboards.contract import WIDGET_SCHEMA_VERSION
from apps.dashboards.models import Dashboard, DashboardWidget, starter_dashboard
from apps.dashboards.widgets import GRID_COLUMNS, GRID_MAX_ROWS, GROUPS, SHAPES, WIDGET_REGISTRY
from apps.tickets.models import Ticket


def agent(username, **kwargs):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role="agent")


class DashboardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = agent("alice")
        self.other = agent("bob")

    def _login(self, user):
        self.client.force_authenticate(user)

    def _board(self, user, name="Overview", **kwargs):
        return Dashboard.objects.create(owner=user, name=name, **kwargs)

    def test_a_user_with_no_dashboard_gets_a_starter_one(self):
        self._login(self.user)
        resp = self.client.get(reverse("dashboards:dashboard-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)
        self.assertTrue(Dashboard.objects.filter(owner=self.user).exists())

    def test_the_starter_dashboard_is_marked_default(self):
        self._login(self.user)
        self.client.get(reverse("dashboards:dashboard-list"))
        board = Dashboard.objects.get(owner=self.user)
        self.assertTrue(board.is_default)
        self.assertEqual(board.name, "Overview")

    def test_the_starter_dashboard_has_widgets(self):
        self._login(self.user)
        resp = self.client.get(reverse("dashboards:dashboard-list"))
        board = resp.json()[0]
        self.assertEqual(len(board["widgets"]), 8)
        self.assertEqual(
            {w["kind"] for w in board["widgets"]},
            {
                "stat_tile",
                "needs_attention",
                "my_work",
                "tickets_by_status",
                "sla_compliance",
            },
        )
        self.assertEqual(DashboardWidget.objects.filter(dashboard__owner=self.user).count(), 8)

    def test_creating_a_second_dashboard_does_not_steal_the_default(self):
        self._login(self.user)
        starter_dashboard(self.user)
        second = self._board(self.user, name="NOC wall")
        resp = self.client.patch(
            reverse("dashboards:dashboard-detail", [second.id]), {"name": "NOC wall 2"}
        )
        self.assertEqual(resp.status_code, 200)
        first = Dashboard.objects.get(name="Overview")
        self.assertTrue(Dashboard.objects.get(pk=first.pk).is_default)
        self.assertFalse(Dashboard.objects.get(pk=second.pk).is_default)

    def test_marking_one_default_clears_the_previous_default(self):
        self._login(self.user)
        first = self._board(self.user, name="One")
        second = self._board(self.user, name="Two")
        resp = self.client.patch(
            reverse("dashboards:dashboard-detail", [second.id]), {"is_default": True}
        )
        self.assertEqual(resp.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)
        defaults = Dashboard.objects.filter(owner=self.user, is_default=True)
        self.assertEqual(defaults.count(), 1)

    def test_two_dashboards_cannot_share_a_name_for_one_owner(self):
        self._board(self.user, name="Overview")
        self._login(self.user)
        resp = self.client.post(
            reverse("dashboards:dashboard-list"), {"name": "Overview"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(reverse("dashboards:dashboard-list"), {"name": "Overview"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Dashboard.objects.filter(owner=self.user, name="Overview").count(), 1)

    def test_two_owners_may_each_have_one_called_overview(self):
        self._board(self.user, name="Overview")
        self._board(self.other, name="Overview")
        self.assertEqual(Dashboard.objects.filter(name="Overview").count(), 2)

    def test_a_stranger_cannot_read_someone_elses_dashboard(self):
        board = self._board(self.user, name="Secret", shared=False)
        self._login(self.other)
        resp = self.client.get(reverse("dashboards:dashboard-detail", [board.id]))
        self.assertEqual(resp.status_code, 404)

    def test_a_shared_dashboard_is_readable_by_anyone(self):
        board = self._board(self.user, name="Shared board", shared=True)
        self._login(self.other)
        resp = self.client.get(reverse("dashboards:dashboard-detail", [board.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["name"], "Shared board")
        self.assertFalse(body["is_mine"])
        self.assertEqual(body["owner"], "alice")
        # shared boards show up in the other user's list
        listing = self.client.get(reverse("dashboards:dashboard-list")).json()
        self.assertIn(str(board.id), [b["id"] for b in listing])

    def test_a_shared_dashboard_is_not_writable_by_a_non_owner(self):
        board = self._board(self.user, name="Shared board", shared=True)
        self._login(self.other)
        detail = reverse("dashboards:dashboard-detail", [board.id])
        resp = self.client.patch(detail, {"name": "Hijack"})
        self.assertEqual(resp.status_code, 403)
        resp = self.client.delete(detail)
        self.assertEqual(resp.status_code, 403)
        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {"widgets": []},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        board.refresh_from_db()
        self.assertEqual(board.name, "Shared board")

    def test_a_layout_of_all_new_widgets_replaces_the_old_ones(self):
        """Widgets the client does not send are gone; ones it sends without an
        id are new."""
        board = starter_dashboard(self.user)
        self._login(self.user)
        new_widgets = [
            {
                "kind": "ticket_list",
                "x": 0,
                "y": 0,
                "w": 6,
                "h": 4,
                "settings": {"saved_view": 3, "limit": 5},
            },
            {"kind": "stat_tile", "x": 6, "y": 0, "w": 3, "h": 2, "settings": {}},
        ]
        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {"widgets": new_widgets},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        board.refresh_from_db()
        widgets = list(board.widgets.all())
        self.assertEqual(len(widgets), 2)
        self.assertEqual({w.kind for w in widgets}, {"ticket_list", "stat_tile"})

    def test_a_widget_keeps_its_id_across_a_save(self):
        """Moving a widget must move it, not destroy and recreate it."""
        board = starter_dashboard(self.user)
        self._login(self.user)
        before = list(board.widgets.all().order_by("y", "x"))
        payload = [
            {
                "id": str(w.id),
                "kind": w.kind,
                "x": w.x,
                "y": w.y + 1,
                "w": w.w,
                "h": w.h,
                "settings": w.settings,
            }
            for w in before
        ]

        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {"widgets": payload},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

        after = {str(w.id): w for w in board.widgets.all()}
        self.assertEqual(set(after), {str(w.id) for w in before}, "a save reminted the widget ids")
        for w in before:
            self.assertEqual(after[str(w.id)].y, w.y + 1)

    def test_a_removed_widget_is_deleted_and_the_rest_survive(self):
        board = starter_dashboard(self.user)
        self._login(self.user)
        before = list(board.widgets.all())
        dropped = before[0]
        payload = [
            {
                "id": str(w.id),
                "kind": w.kind,
                "x": w.x,
                "y": w.y,
                "w": w.w,
                "h": w.h,
                "settings": w.settings,
            }
            for w in before[1:]
        ]

        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {"widgets": payload},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

        remaining = {str(w.id) for w in board.widgets.all()}
        self.assertNotIn(str(dropped.id), remaining)
        self.assertEqual(remaining, {str(w.id) for w in before[1:]})

    def test_two_saves_in_a_row_are_stable(self):
        """Save, read, save again, and the board must be the same board."""
        board = starter_dashboard(self.user)
        self._login(self.user)

        def save():
            payload = [
                {
                    "id": str(w.id),
                    "kind": w.kind,
                    "x": w.x,
                    "y": w.y,
                    "w": w.w,
                    "h": w.h,
                    "settings": w.settings,
                }
                for w in board.widgets.all()
            ]
            r = self.client.put(
                reverse("dashboards:dashboard-layout", [board.id]),
                {"widgets": payload},
                format="json",
            )
            self.assertEqual(r.status_code, 200)
            return {(str(w.id), w.kind, w.x, w.y, w.w, w.h) for w in board.widgets.all()}

        first = save()
        second = save()
        self.assertEqual(first, second)

    def test_an_unknown_widget_kind_is_refused_by_name(self):
        board = starter_dashboard(self.user)
        self._login(self.user)
        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {"widgets": [{"kind": "not_a_widget", "x": 0, "y": 0, "w": 3, "h": 2}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not_a_widget", resp.json()["error"])
        self.assertEqual(board.widgets.count(), 8)  # original layout intact

    def test_a_widget_wider_than_the_grid_is_clamped(self):
        board = starter_dashboard(self.user)
        self._login(self.user)
        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {"widgets": [{"kind": "ticket_list", "x": 0, "y": 0, "w": 40, "h": 99}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        widget = board.widgets.get(kind="ticket_list")
        self.assertEqual(widget.w, GRID_COLUMNS)

    def test_a_widget_with_no_size_is_refused_rather_than_resized(self):
        """Absent geometry used to fall back to the registry default.

        Gridstack's save() drops w when the width equals the widget's own
        minimum, so the browser really did send widgets with no size — and the
        server grew each one to catalogue size, which reflowed the whole grid.
        A request that cannot say how big a widget is, is incomplete.
        """
        board = starter_dashboard(self.user)
        self._login(self.user)
        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {"widgets": [{"kind": "ticket_list", "x": 0, "y": 0}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("w and h", resp.json()["error"])
        self.assertEqual(board.widgets.count(), 8)  # original layout intact

    def test_a_minimum_sized_widget_survives_a_save_round_trip(self):
        """The shape of the scramble: a widget saved at its minimum must read
        back at its minimum, not at the catalogue default."""
        board = starter_dashboard(self.user)
        self._login(self.user)
        spec = WIDGET_REGISTRY["ticket_list"]
        self.assertNotEqual(spec["min_w"], spec["w"], "this test is meaningless if min == default")
        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {
                "widgets": [
                    {"kind": "ticket_list", "x": 0, "y": 0, "w": spec["min_w"], "h": spec["min_h"]}
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        widget = board.widgets.get(kind="ticket_list")
        self.assertEqual((widget.w, widget.h), (spec["min_w"], spec["min_h"]))
        # And again, from the values the API just handed back.
        row = resp.json()["widgets"][0]
        self.assertEqual((row["w"], row["h"]), (spec["min_w"], spec["min_h"]))

    def test_a_widget_smaller_than_its_minimum_is_clamped(self):
        board = starter_dashboard(self.user)
        self._login(self.user)
        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {"widgets": [{"kind": "ticket_list", "x": 0, "y": 0, "w": 1, "h": 1}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        widget = board.widgets.get(kind="ticket_list")
        self.assertEqual(widget.w, WIDGET_REGISTRY["ticket_list"]["min_w"])
        self.assertEqual(widget.h, WIDGET_REGISTRY["ticket_list"]["min_h"])

    def test_unknown_settings_keys_are_dropped(self):
        board = starter_dashboard(self.user)
        self._login(self.user)
        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {
                "widgets": [
                    {
                        "kind": "ticket_list",
                        "x": 0,
                        "y": 0,
                        "w": 6,
                        "h": 4,
                        "settings": {"stat": "open", "injected": "payload", "limit": "7"},
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        widget = board.widgets.get(kind="ticket_list")
        # Asserted by intent rather than by whole-dict equality: the point is
        # that the injected key is gone, and every widget also carries the
        # universal ones.
        self.assertNotIn("injected", widget.settings)
        self.assertNotIn("stat", widget.settings)
        self.assertEqual(widget.settings["limit"], 7)

    def test_an_out_of_range_int_setting_is_clamped(self):
        board = starter_dashboard(self.user)
        self._login(self.user)
        layout = reverse("dashboards:dashboard-layout", [board.id])
        resp = self.client.put(
            layout,
            {
                "widgets": [
                    {
                        "kind": "ticket_list",
                        "x": 0,
                        "y": 0,
                        "w": 6,
                        "h": 4,
                        "settings": {"limit": 9999},
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        widget = board.widgets.get(kind="ticket_list")
        self.assertEqual(widget.settings["limit"], 50)
        resp = self.client.put(
            layout,
            {
                "widgets": [
                    {
                        "kind": "ticket_list",
                        "x": 0,
                        "y": 0,
                        "w": 6,
                        "h": 4,
                        "settings": {"limit": 0},
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        widget = board.widgets.get(kind="ticket_list")
        self.assertEqual(widget.settings["limit"], 1)

    def test_a_choice_setting_outside_its_options_falls_back_to_the_default(self):
        board = starter_dashboard(self.user)
        self._login(self.user)
        resp = self.client.put(
            reverse("dashboards:dashboard-layout", [board.id]),
            {
                "widgets": [
                    {
                        "kind": "stat_tile",
                        "x": 0,
                        "y": 0,
                        "w": 3,
                        "h": 2,
                        "settings": {"stat": "catastrophic"},
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        widget = board.widgets.get(kind="stat_tile")
        self.assertEqual(widget.settings["stat"], "open")

    def test_the_catalog_lists_every_registered_widget(self):
        self._login(self.user)
        resp = self.client.get(reverse("dashboards:dashboard-catalog"))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(sorted(body["widgets"]), sorted(WIDGET_REGISTRY))
        # Compared against the registry, not a literal: the count is expected
        # to grow, and a test that has to be edited to add a widget is noise.
        self.assertEqual(len(body["widgets"]), len(WIDGET_REGISTRY))
        self.assertEqual(body["grid_columns"], GRID_COLUMNS)
        for kind, entry in body["widgets"].items():
            for field in ("label", "w", "h", "min_w", "min_h", "settings"):
                self.assertIn(field, entry, f"{kind} has no {field!r}")

    def test_deleting_a_dashboard_takes_its_widgets_with_it(self):
        board = starter_dashboard(self.user)
        self._login(self.user)
        self.assertEqual(board.widgets.count(), 8)
        resp = self.client.delete(reverse("dashboards:dashboard-detail", [board.id]))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Dashboard.objects.filter(pk=board.pk).exists())
        self.assertEqual(DashboardWidget.objects.filter(dashboard_id=board.pk).count(), 0)


class StarterRaceTests(TestCase):
    """The starter dashboard is created from a GET, and a fresh user's browser
    issues more than one of those before the first paint."""

    def setUp(self):
        self.user = agent("racer")

    def test_creating_the_starter_dashboard_twice_is_harmless(self):
        first = starter_dashboard(self.user)
        second = starter_dashboard(self.user)
        self.assertEqual(first.pk, second.pk)

    def test_the_second_attempt_does_not_duplicate_the_widgets(self):
        starter_dashboard(self.user)
        starter_dashboard(self.user)
        self.assertEqual(DashboardWidget.objects.filter(dashboard__owner=self.user).count(), 8)

    def test_listing_twice_leaves_exactly_one_dashboard(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("dashboards:dashboard-list")
        client.get(url)
        client.get(url)
        self.assertEqual(Dashboard.objects.filter(owner=self.user).count(), 1)

    def test_a_duplicate_name_is_refused_rather_than_erroring(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("dashboards:dashboard-list")
        client.post(url, {"name": "Twice"}, format="json")
        resp = client.post(url, {"name": "Twice"}, format="json")
        self.assertEqual(resp.status_code, 400)


class WidgetHeightTests(TestCase):
    def setUp(self):
        self.user = agent("tall")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.board = starter_dashboard(self.user)
        self.layout = reverse("dashboards:dashboard-layout", [self.board.id])

    def test_a_widget_may_be_taller_than_the_grid_is_wide(self):
        """Rows and columns are different axes. Clamping height to the column
        count capped every widget at 12 rows for no reason."""
        resp = self.client.put(
            self.layout,
            {"widgets": [{"kind": "volume_trend", "x": 0, "y": 0, "w": 6, "h": 16}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.board.widgets.get(kind="volume_trend").h, 16)

    def test_an_absurdly_tall_widget_is_still_clamped(self):
        resp = self.client.put(
            self.layout,
            {"widgets": [{"kind": "volume_trend", "x": 0, "y": 0, "w": 6, "h": 999}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.board.widgets.get(kind="volume_trend").h, GRID_MAX_ROWS)


class DashboardShareTests(TestCase):
    """POST /dashboards/api/<id>/share/ — sharing is ungated; the owner sets it."""

    def setUp(self):
        self.owner = agent("own")
        self.other = agent("oth")
        self.board = starter_dashboard(self.owner)
        self.url = reverse("dashboards:dashboard-share", [self.board.id])

    def _post(self, user, shared):
        client = APIClient()
        client.force_authenticate(user)
        return client.post(self.url, {"shared": shared}, format="json")

    def test_owner_can_share_and_unshare(self):
        r = self._post(self.owner, True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["shared"])
        self.assertTrue(Dashboard.objects.get(pk=self.board.pk).shared)

        r = self._post(self.owner, False)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["shared"])
        self.assertFalse(Dashboard.objects.get(pk=self.board.pk).shared)

    def test_a_non_owner_cannot_share_someone_elses_dashboard(self):
        # A shared board answers 403…
        self.board.shared = True
        self.board.save(update_fields=["shared"])
        r = self._post(self.other, False)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"], "only the owner may share this dashboard")
        self.assertTrue(Dashboard.objects.get(pk=self.board.pk).shared)

        # …and a private one 404.
        self.board.shared = False
        self.board.save(update_fields=["shared"])
        r = self._post(self.other, True)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"error": "not found"})
        self.assertFalse(Dashboard.objects.get(pk=self.board.pk).shared)

    def test_sharing_does_not_make_the_dashboard_writable_by_others(self):
        self.board.shared = True
        self.board.save(update_fields=["shared"])
        client = APIClient()
        client.force_authenticate(self.other)
        detail = reverse("dashboards:dashboard-detail", [self.board.id])
        r = client.patch(detail, {"name": "hijack"}, format="json")
        self.assertEqual(r.status_code, 403)
        r = client.put(
            reverse("dashboards:dashboard-layout", [self.board.id]),
            {"widgets": [{"kind": "my_work", "x": 0, "y": 0, "w": 6, "h": 5, "settings": {}}]},
            format="json",
        )
        self.assertEqual(r.status_code, 403)
        r = client.delete(detail)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Dashboard.objects.filter(pk=self.board.pk).count(), 1)
        self.assertEqual(Dashboard.objects.get(pk=self.board.pk).name, "Overview")


class RegistryShapeTests(TestCase):
    """The rail and the settings form are generated from the registry, so a
    malformed entry is a broken screen rather than an exception."""

    SETTING_TYPES = {"choice", "int", "text", "bool"}

    def test_every_widget_declares_the_fields_the_ui_reads(self):
        for kind, spec in WIDGET_REGISTRY.items():
            for field in ("group", "label", "description", "w", "h", "min_w", "min_h"):
                self.assertIn(field, spec, f"{kind} is missing {field!r}")

    def test_every_widget_is_in_a_known_group(self):
        for kind, spec in WIDGET_REGISTRY.items():
            self.assertIn(spec["group"], GROUPS, f"{kind} has group {spec['group']!r}")

    def test_every_widget_declares_a_contract_shape(self):
        for kind, spec in WIDGET_REGISTRY.items():
            self.assertIn(spec["shape"], SHAPES, f"{kind} has shape {spec['shape']!r}")

    def test_every_setting_has_a_type_the_form_can_render(self):
        for kind, spec in WIDGET_REGISTRY.items():
            for name, field in (spec.get("settings") or {}).items():
                self.assertIn("type", field, f"{kind}.{name} has no type")
                self.assertIn(
                    field["type"],
                    self.SETTING_TYPES,
                    f"{kind}.{name} is type {field['type']!r}, which no form renders",
                )
                self.assertIn("label", field, f"{kind}.{name} has no label")
                self.assertIn("default", field, f"{kind}.{name} has no default")

    def test_a_choice_setting_offers_options_containing_its_default(self):
        for kind, spec in WIDGET_REGISTRY.items():
            for name, field in (spec.get("settings") or {}).items():
                if field["type"] != "choice":
                    continue
                self.assertIn("options", field, f"{kind}.{name} is a choice with no options")
                self.assertIn(
                    field["default"],
                    field["options"],
                    f"{kind}.{name} defaults outside its own options",
                )

    def test_default_sizes_respect_their_own_minimums(self):
        for kind, spec in WIDGET_REGISTRY.items():
            self.assertGreaterEqual(spec["w"], spec["min_w"], f"{kind} w < min_w")
            self.assertGreaterEqual(spec["h"], spec["min_h"], f"{kind} h < min_h")
            self.assertLessEqual(spec["w"], GRID_COLUMNS, f"{kind} is wider than the grid")

    def test_the_catalog_reports_the_group_for_each_widget(self):
        user = agent("cat")
        client = APIClient()
        client.force_authenticate(user)
        body = client.get(reverse("dashboards:dashboard-catalog")).json()
        self.assertEqual(len(body["widgets"]), len(WIDGET_REGISTRY))
        for entry in body["widgets"].values():
            self.assertIn("group", entry, "a widget reaches the UI with no group")


class WidgetDataEndpointTests(TestCase):
    """GET /dashboards/api/widgets/<kind>/data/ — one envelope per widget."""

    def setUp(self):
        self.agent = agent("wagent")
        self.customer = User.objects.create_user("wcust", "wc@x.com", "pw", role="customer")
        self.client = APIClient()
        self.client.force_authenticate(self.agent)

    def test_returns_the_envelope(self):
        resp = self.client.get(reverse("dashboards:widget-data", args=["stat_tile"]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["shape"], "stat")
        self.assertEqual(body["version"], 1)

    def test_settings_come_from_the_query_string(self):
        url = reverse("dashboards:widget-data", args=["stat_tile"])
        data = self.client.get(f"{url}?stat=critical").json()["data"]
        self.assertEqual(data["label"], "Critical")

    def test_out_of_range_setting_is_clamped(self):
        for i in range(60):
            Ticket.objects.create(
                title=f"Mine {i}", created_by=self.customer, assigned_to=self.agent
            )
        url = reverse("dashboards:widget-data", args=["my_work"])
        body = self.client.get(f"{url}?limit=999").json()
        self.assertEqual(len(body["data"]["items"]), 50)

    def test_unknown_kind_is_404(self):
        resp = self.client.get(reverse("dashboards:widget-data", args=["nope"]))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "unknown widget kind: 'nope'"})

    def test_customer_gets_403(self):
        self.client.force_authenticate(self.customer)
        resp = self.client.get(reverse("dashboards:widget-data", args=["stat_tile"]))
        self.assertEqual(resp.status_code, 403)

    def test_catalog_reports_schema_version(self):
        resp = self.client.get(reverse("dashboards:dashboard-catalog"))
        self.assertEqual(resp.json()["schema_version"], WIDGET_SCHEMA_VERSION)


class CustomerAccessTests(TestCase):
    """Dashboards are staff surfaces. A customer is refused everywhere."""

    def setUp(self):
        self.agent = agent("staff")
        self.customer = User.objects.create_user("cust", "c@x.com", "pw", role="customer")
        self.board = starter_dashboard(self.agent)
        self.client = APIClient()
        self.client.force_authenticate(self.customer)

    def test_customer_gets_403_from_every_endpoint(self):
        list_url = reverse("dashboards:dashboard-list")
        catalog_url = reverse("dashboards:dashboard-catalog")
        detail_url = reverse("dashboards:dashboard-detail", [self.board.id])
        layout_url = reverse("dashboards:dashboard-layout", [self.board.id])
        share_url = reverse("dashboards:dashboard-share", [self.board.id])

        self.assertEqual(self.client.get(list_url).status_code, 403)
        self.assertEqual(self.client.get(catalog_url).status_code, 403)
        self.assertEqual(self.client.get(detail_url).status_code, 403)
        self.assertEqual(self.client.patch(detail_url, {"name": "stolen"}).status_code, 403)
        self.assertEqual(self.client.delete(detail_url).status_code, 403)
        self.assertEqual(
            self.client.put(layout_url, {"widgets": []}, format="json").status_code, 403
        )
        self.assertEqual(
            self.client.post(share_url, {"shared": True}, format="json").status_code, 403
        )

    def test_anonymous_is_refused(self):
        client = APIClient()
        resp = client.get(reverse("dashboards:dashboard-list"))
        self.assertIn(resp.status_code, (401, 403))

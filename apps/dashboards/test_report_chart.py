"""The ``report_chart`` widget: one saved report's card on a dashboard.

A customer has no visible reports at all, so the widget cannot distinguish
their own report from someone else's — for them every card reads as removed.
"""

import uuid

from django.test import TestCase
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from apps.dashboards.contract import WIDGET_SCHEMA_VERSION, validate_payload
from apps.dashboards.data import widget_data
from apps.dashboards.widgets import GROUPS, WIDGET_REGISTRY
from apps.projects.test_backlog import make_user
from apps.reports.models import Report

CARD = "card"


class ReportChartTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.other = make_user("bram", "agent")
        self.customer = make_user("boa", "customer")
        self.report = Report.objects.create(
            name="Ops weekly",
            owner=self.agent,
            widgets=[
                {"kind": "ticket_volume"},
                {"kind": "status_mix", "title": "Where tickets sit"},
            ],
        )

    def card(self, index):
        return f"{self.report.id}:{index}"

    def data(self, ref, user=None):
        return widget_data("report_chart", {CARD: ref}, user or self.agent)


class RegistryTests(ReportChartTests):
    def test_registry_lists_report_chart_in_work(self):
        self.assertIn("work", GROUPS)
        spec = WIDGET_REGISTRY["report_chart"]
        self.assertEqual(spec["group"], "work")
        self.assertEqual(spec["label"], "Report chart")
        self.assertEqual(spec["description"], "One card from a saved report.")
        for key, want in (("w", 6), ("h", 4), ("min_w", 3), ("min_h", 3)):
            self.assertEqual(spec[key], want, key)
        field = spec["settings"]["card"]
        self.assertEqual(field["type"], "report_card")
        self.assertEqual(field["label"], "Report card")
        self.assertEqual(field["default"], "")

    def test_a_card_setting_is_trimmed_and_bounded(self):
        from apps.dashboards.widgets import clean_settings

        cleaned = clean_settings("report_chart", {CARD: f" {self.card(0)}{'x' * 90} "})
        self.assertEqual(cleaned[CARD], f"{self.card(0)}{'x' * (60 - len(self.card(0)))}")


class DrawTests(ReportChartTests):
    def test_report_chart_draws_the_card_with_its_shape(self):
        payload = self.data(self.card(0))
        self.assertEqual(payload["version"], WIDGET_SCHEMA_VERSION)
        self.assertEqual(payload["shape"], "series")
        self.assertEqual(payload["title"], "Ticket volume")
        validate_payload(payload["shape"], payload["data"])

    def test_the_cards_own_title_beats_the_registrys(self):
        payload = self.data(self.card(1))
        self.assertEqual(payload["title"], "Where tickets sit")
        self.assertEqual(payload["shape"], "series")

    def test_report_chart_respects_report_visibility(self):
        mine = Report.objects.create(
            name="Private plans", owner=self.other, widgets=[{"kind": "ticket_volume"}]
        )
        removed = self.data(f"{mine.id}:0")["data"]
        self.assertEqual(removed["label"], "This report was removed")

        # A shared report is visible to every agent — but not to a customer,
        # who has no visible reports and so cannot tell it from a removed one.
        mine.shared = True
        mine.save(update_fields=["shared"])
        payload = self.data(f"{mine.id}:0")
        self.assertEqual(payload["shape"], "series")
        self.assertEqual(payload["title"], "Ticket volume")
        self.assertEqual(
            self.data(f"{mine.id}:0", self.customer)["data"]["label"],
            "This report was removed",
        )


class RemovedTests(ReportChartTests):
    def assertRemoved(self, ref, user=None):
        payload = self.data(ref, user) if user is not None else self.data(ref)
        self.assertEqual(payload["version"], WIDGET_SCHEMA_VERSION)
        self.assertEqual(payload["shape"], "stat")
        self.assertEqual(
            payload["data"], {"value": 0, "label": "This report was removed", "tone": "muted"}
        )

    def test_report_chart_says_removed_for_a_deleted_report_or_card(self):
        self.assertRemoved(f"{uuid.uuid4()}:0")
        self.assertRemoved(self.card(9))
        self.assertRemoved("junk")

    def test_a_customer_cannot_draw_a_report_at_all(self):
        # visible_reports gives a customer nothing, so even their own report
        # reads as removed rather than leaking that it exists.
        self.assertRemoved(self.card(0), user=self.customer)

    def test_report_chart_empty_setting_asks_for_a_pick(self):
        payload = self.data("")
        self.assertEqual(payload["version"], WIDGET_SCHEMA_VERSION)
        self.assertEqual(payload["shape"], "stat")
        self.assertEqual(
            payload["data"],
            {
                "value": 0,
                "label": "Pick a report card in this widget's settings.",
                "tone": "muted",
            },
        )


class OptionsTests(ReportChartTests):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.url = reverse("dashboards:dashboard-options-report-card")

    def test_report_card_options_list_visible_cards(self):
        self.client.force_authenticate(self.agent)
        body = self.client.get(self.url).json()
        self.assertIn(["", "Pick a report card"], body)
        self.assertEqual(
            [row[0] for row in body], ["", self.card(0), self.card(1)], "one option per card"
        )
        self.assertIn([self.card(0), "Ops weekly — Ticket volume"], body)
        self.assertIn([self.card(1), "Ops weekly — Where tickets sit"], body)

    def test_reports_are_offered_by_name(self):
        Report.objects.create(name="Alpha first", owner=self.agent, widgets=[{"kind": "velocity"}])
        self.client.force_authenticate(self.agent)
        values = [row[0] for row in self.client.get(self.url).json()]
        self.assertEqual(values[1], f"{Report.objects.get(name='Alpha first').id}:0")

    def test_a_customer_gets_no_cards_and_a_403(self):
        self.report.shared = True
        self.report.save(update_fields=["shared"])
        self.client.force_authenticate(self.customer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

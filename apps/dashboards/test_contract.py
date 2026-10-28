"""The data contract refuses payloads a renderer could not draw."""

from django.test import SimpleTestCase

from apps.dashboards.contract import (
    WIDGET_SCHEMA_VERSION,
    envelope,
    validate_payload,
)


class ContractTests(SimpleTestCase):
    GOOD = {
        "stat": {"value": 7, "label": "Open", "tone": "info", "href": "/tickets/", "sub": "now"},
        "list": {
            "items": [
                {
                    "title": "#1 Boot",
                    "href": "/tickets/1/",
                    "meta": "Open",
                    "badge": "High",
                    "tone": "warn",
                }
            ],
            "empty": "Nothing here.",
        },
        "table": {"columns": ["Agent", "Open"], "rows": [["Ann", 3], ["Bob", 0]]},
        "gauge": {"value": 92.5, "label": "Resolved within SLA", "tone": "ok", "sub": "8 tickets"},
        "series": {
            "kind": "bar",
            "labels": ["Open", "Closed"],
            "series": [{"name": "Tickets", "values": [4, 1]}],
        },
    }

    def assert_refuses(self, shape, data, fragment=""):
        with self.assertRaises(ValueError) as ctx:
            validate_payload(shape, data)
        if fragment:
            self.assertIn(fragment, str(ctx.exception))

    def test_a_valid_payload_of_each_shape_passes(self):
        for shape, data in self.GOOD.items():
            validate_payload(shape, data)  # must not raise

    def test_stat_refuses_a_string_value(self):
        self.assert_refuses("stat", {"value": "7", "label": "Open"}, "number")

    def test_stat_refuses_a_bool_value(self):
        self.assert_refuses("stat", {"value": True, "label": "Open"}, "number")

    def test_unknown_tone_is_refused(self):
        self.assert_refuses("stat", {"value": 1, "label": "Open", "tone": "purple"}, "tone")

    def test_list_needs_empty_text(self):
        self.assert_refuses("list", {"items": []}, "empty")

    def test_table_rows_must_match_columns(self):
        self.assert_refuses("table", {"columns": ["a", "b"], "rows": [["only one"]]}, "2")

    def test_gauge_accepts_none_and_refuses_101(self):
        validate_payload("gauge", {"value": None, "label": "Resolved within SLA"})
        self.assert_refuses("gauge", {"value": 101, "label": "SLA"}, "101")

    def test_series_values_must_match_labels(self):
        self.assert_refuses(
            "series",
            {"kind": "line", "labels": ["a", "b"], "series": [{"name": "S", "values": [1]}]},
            "labels",
        )

    def test_series_kind_must_be_bar_or_line(self):
        self.assert_refuses(
            "series",
            {"kind": "pie", "labels": ["a"], "series": [{"name": "S", "values": [1]}]},
            "pie",
        )

    def test_contract_accepts_area_and_stacked_bar(self):
        for kind in ("area", "stacked-bar"):
            validate_payload(
                "series",
                {
                    "kind": kind,
                    "labels": ["Mon", "Tue"],
                    "series": [
                        {"name": "S1", "values": [1, 2]},
                        {"name": "S2", "values": [3, 0]},
                    ],
                },
            )

    def test_contract_still_refuses_an_unknown_kind(self):
        self.assert_refuses(
            "series",
            {"kind": "pie", "labels": ["Mon"], "series": [{"name": "S", "values": [1]}]},
            "pie",
        )

    def test_unknown_shape_is_refused(self):
        self.assert_refuses("heatmap", {}, "heatmap")

    def test_envelope_carries_the_version(self):
        got = envelope("stat", {"value": 2, "label": "Open"})
        self.assertEqual(got["version"], WIDGET_SCHEMA_VERSION)
        self.assertEqual(got["shape"], "stat")
        self.assertEqual(got["data"], {"value": 2, "label": "Open"})

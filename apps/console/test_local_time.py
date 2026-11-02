import datetime as dt
from zoneinfo import ZoneInfo

from django.template import Context, Template
from django.test import SimpleTestCase


class LocalTimeTagTests(SimpleTestCase):
    def render(self, value, style=""):
        tpl = Template("{% load local_time %}{% local_time value " + style + " %}")
        return tpl.render(Context({"value": value}))

    def test_writes_labelled_utc_inside_a_time_element(self):
        when = dt.datetime(2026, 10, 29, 9, 5, tzinfo=dt.UTC)
        html = self.render(when)
        self.assertIn('datetime="2026-10-29T09:05:00+00:00"', html)
        self.assertIn('data-local="datetime"', html)
        self.assertIn("29 Oct 2026, 09:05 UTC", html)

    def test_converts_other_zones_to_utc(self):
        when = dt.datetime(2026, 10, 29, 5, 5, tzinfo=ZoneInfo("America/New_York"))
        self.assertIn("Oct 29, 09:05 UTC", self.render(when, '"short"'))

    def test_empty_value_renders_nothing(self):
        self.assertEqual(self.render(None), "")

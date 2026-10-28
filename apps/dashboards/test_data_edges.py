"""Envelope and boundary behaviour of ``dashboards.data`` the main suite skips:
empty databases, deleted saved views, breached-only windows, one-day ranges.

Same SLA-receiver caveat as ``test_data.py``: creating a Ticket stamps its own
due dates, so tests that need a specific ``resolution_due`` overwrite it with
an immediate queryset update afterwards.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.dashboards.contract import validate_payload
from apps.dashboards.data import volume_trend, widget_data
from apps.dashboards.widgets import WIDGET_REGISTRY, default_settings
from apps.tickets.models import Ticket


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class EmptyDatabaseWidgetTests(TestCase):
    """Every registry kind still answers with a valid envelope once the
    ticket tables hold nothing an earlier migration left behind."""

    def setUp(self):
        self.agent = make_user("empty-agent", "agent")
        Ticket.objects.all().delete()

    def test_every_kind_returns_a_valid_envelope_on_an_empty_database(self):
        for kind, spec in WIDGET_REGISTRY.items():
            payload = widget_data(kind, default_settings(kind), self.agent)
            self.assertEqual(payload["version"], 1, kind)
            self.assertEqual(payload["shape"], spec["shape"], kind)
            validate_payload(spec["shape"], payload["data"])

    def test_list_widgets_report_their_empty_message_on_an_empty_database(self):
        for kind in ("ticket_list", "needs_attention", "my_work"):
            data = widget_data(kind, default_settings(kind), self.agent)["data"]
            self.assertEqual(data["items"], [], kind)
            self.assertTrue(data["empty"], kind)

    def test_sla_compliance_has_no_value_on_an_empty_database(self):
        data = widget_data("sla_compliance", {}, self.agent)["data"]
        self.assertIsNone(data["value"])


class WidgetBoundaryTests(TestCase):
    def setUp(self):
        self.agent = make_user("edge-agent", "agent")
        self.customer = make_user("edge-customer", "customer")
        Ticket.objects.all().delete()

    def ticket(self, **kwargs):
        due = kwargs.pop("resolution_due", None)
        breached = kwargs.pop("resolution_breached", False)
        created_at = kwargs.pop("created_at", None)
        kwargs.setdefault("created_by", self.customer)
        t = Ticket.objects.create(**kwargs)
        # auto_now_add ignores a passed created_at, so backdate via the table.
        fields = {"first_response_due": None}
        if due is not None or breached:
            fields.update(resolution_due=due, resolution_breached=breached)
        if created_at is not None:
            fields["created_at"] = created_at
        Ticket.objects.filter(pk=t.pk).update(**fields)
        t.refresh_from_db()
        return t

    # -- volume_trend -------------------------------------------------------

    def test_volume_trend_with_a_one_day_range_has_today_as_its_only_label(self):
        # The registry clamps range_days to its min of 7, so the one-day
        # window is reached through the data function directly.
        settings = {**default_settings("volume_trend"), "range_days": 1}
        data = volume_trend(settings, self.agent)
        self.assertEqual(data["labels"], [timezone.localdate().isoformat()])
        for series in data["series"]:
            self.assertEqual(len(series["values"]), 1, series["name"])

    # -- sla_compliance -----------------------------------------------------

    def test_sla_compliance_is_zero_and_bad_when_every_ticket_breached(self):
        now = timezone.now()
        for i in range(2):
            self.ticket(
                title=f"Edge breached {i}",
                status="resolved",
                closed_at=now - timedelta(days=1),
                resolution_due=now - timedelta(days=2),
                resolution_breached=True,
            )
        data = widget_data("sla_compliance", {"range_days": 30}, self.agent)["data"]
        self.assertEqual(data["value"], 0.0)
        self.assertEqual(data["tone"], "bad")
        self.assertEqual(data["sub"], "2 tickets, last 30 days")

    # -- agent_load ---------------------------------------------------------

    def test_agent_load_with_only_an_admin_still_returns_the_admin_row(self):
        admin = make_user("edge-admin", "admin")
        User.objects.filter(role="agent").delete()
        data = widget_data("agent_load", {}, admin)["data"]
        self.assertEqual(data["columns"], ["Agent", "Open", "Critical"])
        self.assertEqual(data["rows"], [[admin.username, 0, 0]])

    # -- stat_tile ----------------------------------------------------------

    def test_stat_tile_counts_match_a_hand_computed_expectation(self):
        now = timezone.now()
        recent = now - timedelta(days=7) + timedelta(hours=1)
        last_week = now - timedelta(days=9)

        self.ticket(
            title="Edge A",
            status="open",
            priority="critical",
            resolution_due=now + timedelta(hours=1),
        )
        self.ticket(
            title="Edge B",
            status="in_progress",
            assigned_to=self.agent,
            created_at=recent,
            resolution_due=now - timedelta(days=1),
            resolution_breached=True,
        )
        self.ticket(
            title="Edge C",
            status="pending",
            assigned_to=self.agent,
            created_at=recent,
            resolution_due=now - timedelta(hours=6),
        )
        self.ticket(
            title="Edge D",
            status="closed",
            priority="critical",
            created_at=last_week,
            closed_at=recent,
            resolution_breached=True,
        )
        self.ticket(
            title="Edge E",
            status="resolved",
            created_at=last_week,
            closed_at=now - timedelta(days=2),
            resolution_due=now - timedelta(days=8),
            resolution_breached=True,
        )
        self.ticket(title="Edge F", status="closed", created_at=last_week, closed_at=last_week)

        # open/unassigned 3/1, overdue 2, breached 1 (the SLA receiver clears
        # the flag when a ticket resolves), critical 1 (`critical` counts only
        # live tickets), created this week 3, resolved this week 2.
        expected = {
            "open": 3,
            "unassigned": 1,
            "overdue": 2,
            "breached": 1,
            "critical": 1,
            "created_week": 3,
            "resolved_week": 2,
        }
        for stat, value in expected.items():
            data = widget_data("stat_tile", {"stat": stat}, self.agent)["data"]
            self.assertEqual(data["value"], value, stat)

    # -- ticket_list --------------------------------------------------------

    def test_ticket_list_of_a_deleted_saved_view_says_it_no_longer_exists(self):
        data = widget_data("ticket_list", {"saved_view": 999_999}, self.agent)["data"]
        self.assertEqual(data["items"], [])
        self.assertEqual(
            data["empty"], "That saved view no longer exists, or is not shared with you."
        )

    # -- needs_attention ----------------------------------------------------

    def test_needs_attention_excludes_resolved_and_closed_even_when_overdue(self):
        now = timezone.now()
        self.ticket(
            title="Edge resolved overdue",
            status="resolved",
            closed_at=now,
            resolution_due=now - timedelta(days=2),
        )
        self.ticket(
            title="Edge closed overdue",
            status="closed",
            closed_at=now,
            resolution_due=now - timedelta(days=2),
        )
        live = self.ticket(title="Edge open overdue", status="open", resolution_due=now)
        data = widget_data("needs_attention", {"limit": 50}, self.agent)["data"]
        titles = [item["title"] for item in data["items"]]
        self.assertEqual(titles, [f"#{live.pk} Edge open overdue"])

"""Each widget kind computes its data from the ticket tables.

Tickets here carry explicit ``resolution_due`` values: creating a Ticket
fires the SLA receiver, which recomputes due dates from priority targets, so
a test that wants a specific due time must overwrite it afterwards.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.dashboards.contract import validate_payload
from apps.dashboards.data import widget_data
from apps.dashboards.widgets import WIDGET_REGISTRY, default_settings
from apps.tickets.models import SavedView, Ticket


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class WidgetDataTests(TestCase):
    def setUp(self):
        self.agent = make_user("agent", "agent")
        self.colleague = make_user("colleague", "agent")
        self.admin = make_user("admin", "admin")
        self.customer = make_user("cust", "customer")
        now = timezone.now()

        def ticket(**kwargs):
            kwargs.setdefault("created_by", self.customer)
            t = Ticket.objects.create(**kwargs)
            due = kwargs.get("resolution_due")
            if "resolution_due" in kwargs and t.resolution_due != due:
                # The SLA receiver stamped its own target; keep the test's.
                Ticket.objects.filter(pk=t.pk).update(
                    resolution_due=due,
                    first_response_due=None,
                    resolution_breached=kwargs.get("resolution_breached", False),
                )
                t.refresh_from_db()
            return t

        self.open_ticket = ticket(title="Open one", status="open", priority="high")
        self.in_progress = ticket(
            title="Working",
            status="in_progress",
            priority="critical",
            assigned_to=self.agent,
            resolution_due=now + timedelta(days=2),
        )
        self.pending = ticket(title="Waiting", status="pending", assigned_to=self.colleague)
        self.overdue = ticket(
            title="Overdue one",
            status="open",
            priority="high",
            assigned_to=self.agent,
            resolution_due=now - timedelta(hours=2),
        )
        self.breached = ticket(
            title="Breached one",
            status="in_progress",
            resolution_due=now - timedelta(days=1),
            resolution_breached=True,
        )
        self.due_soon = ticket(
            title="Due soon",
            status="open",
            priority="low",
            resolution_due=now + timedelta(hours=1),
        )
        self.resolved = ticket(
            title="Resolved one",
            status="resolved",
            priority="low",
            closed_at=now - timedelta(days=1),
            resolution_due=now + timedelta(days=1),
        )

    def data(self, kind, **settings):
        raw = {**default_settings(kind), **settings}
        return widget_data(kind, raw, self.agent)["data"]

    # -- envelope ----------------------------------------------------------

    def test_every_registry_kind_returns_a_valid_envelope(self):
        for kind, spec in WIDGET_REGISTRY.items():
            payload = widget_data(kind, {}, self.agent)
            self.assertEqual(payload["version"], 1, kind)
            self.assertEqual(payload["shape"], spec["shape"], kind)
            validate_payload(spec["shape"], payload["data"])

    # -- stat_tile ---------------------------------------------------------

    def test_stat_open_counts_open_in_progress_and_pending(self):
        data = self.data("stat_tile", stat="open")
        self.assertEqual(data["value"], 6)
        self.assertEqual(data["label"], "Open")
        self.assertEqual(data["href"], reverse("tickets:ticket_list"))

    def test_stat_unassigned(self):
        data = self.data("stat_tile", stat="unassigned")
        # open, overdue one (assigned), due soon, breached — the last is unassigned.
        self.assertEqual(data["value"], 3)
        self.assertEqual(data["label"], "Unassigned")
        self.assertIn("?assigned=unassigned", data["href"])

    def test_stat_overdue(self):
        data = self.data("stat_tile", stat="overdue")
        self.assertEqual(data["value"], 2)  # overdue + breached, both due in the past
        self.assertEqual(data["tone"], "bad")

    def test_stat_breached(self):
        data = self.data("stat_tile", stat="breached")
        self.assertEqual(data["value"], 1)
        self.assertEqual(data["label"], "SLA breached")
        self.assertEqual(data["tone"], "bad")

    def test_stat_critical(self):
        data = self.data("stat_tile", stat="critical")
        self.assertEqual(data["value"], 1)
        self.assertIn("?priority=critical", data["href"])

    def test_stat_zero_tone_is_ok_for_an_alarm_stat(self):
        Ticket.objects.filter(resolution_breached=True).update(resolution_breached=False)
        self.assertEqual(self.data("stat_tile", stat="breached")["tone"], "ok")

    def test_stat_created_week(self):
        old = Ticket.objects.create(title="Last month", created_by=self.customer, status="closed")
        # created_at is auto_now_add: a queryset update is the only way to put
        # a ticket outside the week without touching the clock.
        Ticket.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))
        data = self.data("stat_tile", stat="created_week")
        self.assertEqual(data["value"], 7)
        self.assertEqual(data["label"], "Created this week")

    def test_stat_resolved_week(self):
        old = Ticket.objects.create(title="Ancient win", status="closed", created_by=self.customer)
        past = timezone.now() - timedelta(days=40)
        Ticket.objects.filter(pk=old.pk).update(created_at=past, closed_at=past)
        data = self.data("stat_tile", stat="resolved_week")
        self.assertEqual(data["value"], 1)  # only this week's resolved one
        self.assertEqual(data["label"], "Resolved this week")

    # -- lists ---------------------------------------------------------------

    def test_needs_attention_orders_by_due_and_marks_overdue_bad(self):
        data = self.data("needs_attention")
        by_title = {item["title"]: item for item in data["items"]}
        overdue_title = f"#{self.overdue.pk} Overdue one"
        due_soon_title = f"#{self.due_soon.pk} Due soon"
        breached_title = f"#{self.breached.pk} Breached one"
        self.assertEqual(
            [item["title"] for item in data["items"]],
            [breached_title, overdue_title, due_soon_title],
        )
        overdue_item = by_title[overdue_title]
        self.assertEqual(overdue_item["tone"], "bad")
        self.assertEqual(overdue_item["meta"], "Overdue")
        self.assertEqual(overdue_item["badge"], "High")
        due_soon_item = by_title[due_soon_title]
        self.assertEqual(due_soon_item["tone"], "warn")
        self.assertEqual(due_soon_item["meta"], "Due soon")
        self.assertEqual(
            overdue_item["href"], reverse("tickets:ticket_detail", args=[self.overdue.pk])
        )
        self.assertEqual(data["empty"], "Nothing is close to its due time.")

    def test_my_work_includes_collaborator_tickets_once(self):
        self.pending.assigned_users.add(self.agent)  # also assigned_to colleague
        data = self.data("my_work")
        titles = [item["title"] for item in data["items"]]
        self.assertEqual(len(titles), len(set(titles)), "collaborator ticket listed twice")
        self.assertIn(f"#{self.in_progress.pk} Working", titles)
        self.assertIn(f"#{self.pending.pk} Waiting", titles)
        item = next(i for i in data["items"] if i["title"].startswith(f"#{self.pending.pk}"))
        self.assertEqual(item["meta"], "Pending")
        self.assertEqual(data["empty"], "Nothing is assigned to you.")

    def test_ticket_list_uses_a_shared_saved_view(self):
        view = SavedView.objects.create(
            name="Critical", owner=self.customer, query="priority=critical", is_shared=True
        )
        data = self.data("ticket_list", saved_view=view.pk)
        titles = [item["title"] for item in data["items"]]
        self.assertEqual(titles, [f"#{self.in_progress.pk} Working"])

    def test_ticket_list_refuses_someone_elses_private_view(self):
        view = SavedView.objects.create(
            name="Mine", owner=self.colleague, query="status=open", is_shared=False
        )
        data = self.data("ticket_list", saved_view=view.pk)
        self.assertEqual(data["items"], [])
        self.assertEqual(
            data["empty"], "That saved view no longer exists, or is not shared with you."
        )

    # -- gauge ---------------------------------------------------------------

    def test_sla_compliance_percent(self):
        # Late win: closed inside the window but breached -> 1 of 2 on time.
        late = Ticket.objects.create(
            title="Late win",
            status="closed",
            created_by=self.customer,
            resolution_due=timezone.now(),
        )
        past = timezone.now() - timedelta(days=2)
        Ticket.objects.filter(pk=late.pk).update(closed_at=past, resolution_breached=True)
        data = self.data("sla_compliance")
        self.assertEqual(data["value"], 50.0)
        self.assertEqual(data["label"], "Resolved within SLA")
        self.assertEqual(data["sub"], "2 tickets, last 30 days")
        self.assertEqual(data["tone"], "bad")

    def test_sla_compliance_with_nothing_is_none(self):
        Ticket.objects.filter(pk=self.resolved.pk).update(resolution_due=None)
        data = self.data("sla_compliance")
        self.assertIsNone(data["value"])
        self.assertEqual(data["sub"], "No resolved tickets with an SLA in the last 30 days")

    # -- series --------------------------------------------------------------

    def test_by_status_includes_zero_statuses(self):
        data = self.data("tickets_by_status")
        self.assertEqual(data["kind"], "bar")
        self.assertEqual(data["labels"], ["Open", "In Progress", "Pending", "Resolved", "Closed"])
        values = data["series"][0]["values"]
        self.assertEqual(values, [3, 2, 1, 1, 0])  # Closed is the zero
        Ticket.objects.filter(pk=self.breached.pk).update(status="closed")
        zeroed = self.data("tickets_by_status")
        self.assertEqual(zeroed["series"][0]["values"], [3, 1, 1, 1, 1])  # now In Progress is

    def test_tickets_by_priority_counts_only_open(self):
        data = self.data("tickets_by_priority")
        self.assertEqual(data["labels"], ["Critical", "High", "Medium", "Low"])
        # open statuses only: critical=in_progress, high=open+overdue,
        # medium=breached+pending, low=due_soon. The resolved one never counts.
        self.assertEqual(data["series"][0]["values"], [1, 2, 2, 1])

    def test_volume_trend_has_one_label_per_day_ending_today(self):
        data = self.data("volume_trend", range_days=7)
        today = timezone.localdate().isoformat()
        self.assertEqual(data["labels"][-1], today)
        self.assertEqual(len(data["labels"]), 7)
        self.assertEqual(data["kind"], "line")
        self.assertEqual([s["name"] for s in data["series"]], ["Created", "Resolved"])
        created = data["series"][0]["values"]
        self.assertEqual(sum(created), 7)  # everything here was made today
        resolved = data["series"][1]["values"]
        self.assertEqual(sum(resolved), 1)  # the resolved one closed yesterday
        self.assertEqual(resolved[-1], 0)  # and nothing today

    # -- table ---------------------------------------------------------------

    def test_agent_load_lists_agents_with_zero(self):
        data = self.data("agent_load")
        self.assertEqual(data["columns"], ["Agent", "Open", "Critical"])
        rows = {row[0]: row for row in data["rows"]}
        self.assertIn("admin", rows)  # an admin with no tickets at all still appears
        self.assertEqual(rows["admin"], ["admin", 0, 0])
        self.assertEqual(rows["agent"], ["agent", 2, 1])
        self.assertNotIn("cust", rows)  # customers are not agents
        opens = [row[1] for row in data["rows"]]
        self.assertEqual(opens, sorted(opens, reverse=True))

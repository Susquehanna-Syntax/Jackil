"""Report compute: registry shape, per-kind data, sources and visibility."""

from datetime import date, datetime, timedelta

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.reports.compute import compute, report_tickets, visible_reports, window
from apps.reports.models import Report
from apps.reports.widgets import GROUPS, QUERIES, REPORT_WIDGETS
from apps.tickets.models import SavedView, Ticket, TicketRating

TODAY = date(2026, 10, 15)


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


def backdate(ticket, **field_times):
    """Write datetime fields straight to the row — auto_now_add ignores .save()."""
    Ticket.objects.filter(pk=ticket.pk).update(**field_times)
    ticket.refresh_from_db()
    return ticket


class ReportTestCase(TestCase):
    def setUp(self):
        self.agent = make_user("agent", "agent")
        self.colleague = make_user("colleague", "agent")
        self.customer = make_user("cust", "customer")
        self.now = timezone.make_aware(datetime(TODAY.year, TODAY.month, TODAY.day, 12, 0))

    def ticket(self, **kwargs):
        kwargs.setdefault("title", "Ticket")
        kwargs.setdefault("created_by", self.customer)
        return Ticket.objects.create(**kwargs)

    def dated_ticket(self, created_at, **kwargs):
        """A ticket whose created_at is *created_at* (an aware datetime)."""
        return backdate(self.ticket(**kwargs), created_at=created_at)

    def closed_ticket(self, **kwargs):
        """A closed ticket carrying exactly the SLA fields it is given. The
        create signal stamps resolution_due from the priority target, so a
        no-limit row must have its cleared afterwards."""
        ticket = self.ticket(**{**kwargs, "status": "closed"})
        stamp = {"created_at": self.now, "closed_at": self.now}
        stamp.update(kwargs)
        ticket = backdate(ticket, **stamp)
        if "resolution_due" not in kwargs:
            Ticket.objects.filter(pk=ticket.pk).update(resolution_due=None)
            ticket.refresh_from_db()
        return ticket

    def report(self, widgets, **kwargs):
        kwargs.setdefault("name", "Weekly")
        kwargs.setdefault("range_days", 7)
        owner = kwargs.pop("owner", self.agent)
        m2m = {k: kwargs.pop(k) for k in ("departments", "saved_views") if k in kwargs}
        report = Report.objects.create(owner=owner, **kwargs)
        for key, value in m2m.items():
            getattr(report, key).set(value)
        report.widgets = widgets
        report.save()
        return report


class RegistryTests(TestCase):
    def test_registry_entries_have_vigils_keys(self):
        keys = {
            "title",
            "description",
            "chart",
            "family",
            "charts",
            "x_label",
            "y_label",
            "how",
            "size",
            "group",
        }
        for kind, entry in REPORT_WIDGETS.items():
            with self.subTest(kind=kind):
                self.assertEqual(set(entry), keys)
                self.assertEqual(entry["chart"], entry["charts"][0])
                self.assertIn(entry["family"], ("days", "rows"))
                self.assertIn(entry["group"], GROUPS)
                self.assertIn(kind, QUERIES)


class ComputeEnvelopeTests(ReportTestCase):
    def test_every_kind_computes_a_valid_envelope(self):
        widgets = []
        for kind, entry in REPORT_WIDGETS.items():
            for chart in entry["charts"]:
                widgets.append({"kind": kind, "chart": chart})
        report = self.report(widgets)
        for index in range(len(widgets)):
            card = widgets[index]
            entry = REPORT_WIDGETS[card["kind"]]
            with self.subTest(kind=card["kind"], chart=card["chart"]):
                result = compute(report, index, self.agent, today=TODAY)
                self.assertEqual(result["version"], 1)
                data = result["data"]
                if card["chart"] == "table":
                    self.assertEqual(result["shape"], "table")
                    if entry["family"] == "days":
                        self.assertEqual(len(data["rows"]), report.range_days)
                        self.assertGreater(len(data["columns"]), 1)
                    else:
                        self.assertEqual(data["columns"], [entry["x_label"], entry["y_label"]])
                else:
                    self.assertEqual(result["shape"], "series")
                    self.assertEqual(data["kind"], card["chart"])
                    if entry["family"] == "days":
                        self.assertEqual(len(data["labels"]), report.range_days)
                        for s in data["series"]:
                            self.assertEqual(len(s["values"]), report.range_days)


class DaysFamilyTests(ReportTestCase):
    def test_ticket_volume_counts_created_and_resolved_per_day(self):
        start = TODAY - timedelta(days=6)
        self.dated_ticket(self.now, title="a")
        self.dated_ticket(self.now, title="b")
        self.dated_ticket(
            timezone.make_aware(datetime(start.year, start.month, start.day, 9)),
            title="old",
            status="resolved",
            closed_at=self.now - timedelta(days=2),
        )

        report = self.report([{"kind": "ticket_volume"}])
        data = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(
            data["labels"],
            [(start + timedelta(days=i)).isoformat() for i in range(7)],
        )
        by_name = {s["name"]: s["values"] for s in data["series"]}
        self.assertEqual(by_name["Created"][-1], 2)
        self.assertEqual(by_name["Resolved"][-3], 1)
        self.assertEqual(sum(by_name["Created"]), 3)

    def test_sla_compliance_percent_per_day(self):
        self.closed_ticket(title="met", resolution_due=self.now + timedelta(hours=1))
        self.closed_ticket(title="breached", resolution_due=self.now - timedelta(hours=1))
        self.closed_ticket(title="no due")

        report = self.report([{"kind": "sla_compliance"}])
        data = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(data["series"][0]["name"], "Within SLA (%)")
        self.assertEqual(data["series"][0]["values"][-1], 50.0)
        self.assertEqual(data["series"][0]["values"][0], 0)

    def test_medians_skip_tickets_without_the_timestamp(self):
        self.dated_ticket(
            self.now - timedelta(hours=2),
            title="responded",
            status="in_progress",
            first_responded_at=self.now,
        )
        self.ticket(title="silent", status="open")

        report = self.report([{"kind": "first_response_time"}])
        values = compute(report, 0, self.agent, today=TODAY)["data"]["series"][0]["values"]
        self.assertEqual(values[-1], 2.0)

        no_close = self.ticket(title="res", status="resolved")
        Ticket.objects.filter(pk=no_close.pk).update(created_at=self.now, resolution_due=None)
        report = self.report([{"kind": "resolution_time"}])
        data = compute(report, 0, self.agent, today=TODAY)
        self.assertEqual(data["data"]["series"][0]["values"][-1], 0)

    def test_csat_average_per_day(self):
        rated = self.ticket(title="rated")
        TicketRating.objects.create(ticket=rated, score=4)
        TicketRating.objects.filter(ticket=rated).update(created_at=self.now)
        older = self.ticket(title="rated2")
        TicketRating.objects.create(ticket=older, score=5)
        TicketRating.objects.filter(ticket=older).update(created_at=self.now - timedelta(days=1))

        report = self.report([{"kind": "csat"}])
        values = compute(report, 0, self.agent, today=TODAY)["data"]["series"][0]["values"]
        self.assertEqual(values[-1], 4.0)
        self.assertEqual(values[-2], 5.0)
        self.assertEqual(values[0], 0)


class RowsFamilyTests(ReportTestCase):
    def test_status_and_priority_mix(self):
        self.ticket(title="o", status="open", priority="high")
        self.ticket(title="p", status="pending", priority="high")
        self.ticket(title="c", status="closed", priority="low")

        report = self.report([{"kind": "status_mix", "chart": "table"}])
        rows = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(rows["columns"], ["Status", "Tickets"])
        self.assertEqual([r[1] for r in rows["rows"]], [1, 0, 1, 0, 1])

        report = self.report([{"kind": "priority_mix"}])
        data = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(data["series"][0]["name"], "Open tickets")
        self.assertEqual(data["labels"], ["Critical", "High", "Medium", "Low"])
        self.assertEqual(data["series"][0]["values"], [0, 2, 0, 0])

    def test_agent_load_orders_by_most_loaded(self):
        for _ in range(2):
            self.ticket(title="for agent", status="open", assigned_to=self.agent)
        self.ticket(title="for colleague", status="in_progress", assigned_to=self.colleague)
        User.objects.create_user("Zed", "zed@x.com", "pw", role="agent")
        report = self.report([{"kind": "agent_load"}])
        data = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(data["series"][0]["name"], "Open tickets")
        self.assertEqual(data["labels"][0], "agent")
        self.assertEqual(data["series"][0]["values"][0], 2)
        # Zero-load agents follow, alphabetical by display name.
        self.assertEqual(data["labels"][1:], ["colleague", "Zed"])


class WindowTests(ReportTestCase):
    def test_range_days_limits_the_window(self):
        self.dated_ticket(self.now - timedelta(days=3), title="recent")
        old = self.dated_ticket(self.now - timedelta(days=40), title="old")
        # Creation stamps the SLA clock too; only created_at matters here.
        backdate(old, first_response_due=None, resolution_due=None)

        thirty = self.report([{"kind": "ticket_volume"}], range_days=30)
        start, end = window(thirty, today=TODAY)
        self.assertEqual((start, end), (TODAY - timedelta(days=29), TODAY))
        values = compute(thirty, 0, self.agent, today=TODAY)["data"]["series"][0]["values"]
        self.assertEqual(sum(values), 1)

        ninety = self.report([{"kind": "ticket_volume"}], range_days=90)
        values = compute(ninety, 0, self.agent, today=TODAY)["data"]["series"][0]["values"]
        self.assertEqual(sum(values), 2)


class SourceTests(ReportTestCase):
    def test_sources_filter_by_department_and_saved_view(self):
        sales = Department.objects.create(name="Sales")
        support = Department.objects.create(name="Support")
        in_sales = self.ticket(title="salesy", department=sales)
        self.ticket(title="supporty", department=support)
        self.ticket(title="critical-unassigned", priority="critical")

        report = self.report([{"kind": "status_mix", "chart": "table"}], departments=[sales])
        rows = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(sum(r[1] for r in rows["rows"]), 1)
        self.assertEqual(
            list(report_tickets(report, self.agent).values_list("pk", flat=True)),
            [in_sales.pk],
        )

        view = SavedView.objects.create(owner=self.agent, query="priority=critical", is_shared=True)
        report = self.report([{"kind": "status_mix", "chart": "table"}], saved_views=[view])
        rows = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(sum(r[1] for r in rows["rows"]), 1)

    def test_card_labels_override_the_registry(self):
        report = self.report(
            [
                {
                    "kind": "status_mix",
                    "chart": "table",
                    "x_label": "State",
                    "y_label": "Count",
                }
            ]
        )
        data = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(data["columns"], ["State", "Count"])

    def test_compute_refuses_customers_and_bad_index(self):
        report = self.report([{"kind": "status_mix"}])
        with self.assertRaises(PermissionDenied):
            compute(report, 0, self.customer, today=TODAY)
        with self.assertRaises(IndexError):
            compute(report, 5, self.agent, today=TODAY)


class VisibilityTests(ReportTestCase):
    def test_visible_reports_owner_and_shared(self):
        mine = self.report([], name="Mine", shared=False)
        theirs_shared = self.report([], name="Theirs", owner=self.colleague, shared=True)
        theirs_private = self.report([], name="Private", owner=self.colleague, shared=False)

        self.assertIn(mine, list(visible_reports(self.agent)))
        self.assertNotIn(theirs_private, list(visible_reports(self.agent)))
        visible_colleague = list(visible_reports(self.colleague))
        self.assertIn(theirs_shared, visible_colleague)
        self.assertNotIn(mine, visible_colleague)
        self.assertEqual(list(visible_reports(self.customer)), [])

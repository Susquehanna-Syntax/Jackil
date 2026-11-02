"""Report compute: registry shape, per-kind data, sources and visibility."""

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.projects import service
from apps.projects.models import CostSettings, PersonRate, Sprint
from apps.projects.permissions import can_see_cost, staff_users
from apps.reports.compute import (
    compute,
    csv_for,
    report_tickets,
    validate_report,
    visible_reports,
    window,
)
from apps.reports.models import Report
from apps.reports.widgets import GROUPS, QUERIES, REPORT_WIDGETS
from apps.tickets.models import SavedView, Ticket, TicketRating
from apps.wiki.models import Page, PageVersion, Space

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
        m2m = {k: kwargs.pop(k) for k in ("departments", "projects", "saved_views") if k in kwargs}
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
        optional = {"source", "needs", "money"}
        for kind, entry in REPORT_WIDGETS.items():
            with self.subTest(kind=kind):
                extra = set(entry) - keys
                self.assertTrue(extra <= optional, f"{kind}: unexpected {sorted(extra)}")
                self.assertEqual(keys - set(entry), set())
                self.assertEqual(entry["chart"], entry["charts"][0])
                self.assertIn(entry["family"], ("days", "rows", "groups"))
                self.assertIn(entry["group"], GROUPS)
                self.assertIn(kind, QUERIES)


class ComputeEnvelopeTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("coral", "admin")

    def test_every_kind_computes_a_valid_envelope(self):
        widgets = []
        for kind, entry in REPORT_WIDGETS.items():
            for chart in entry["charts"]:
                widgets.append({"kind": kind, "chart": chart})
        report = self.report(widgets, owner=self.admin)
        for index in range(len(widgets)):
            card = widgets[index]
            entry = REPORT_WIDGETS[card["kind"]]
            with self.subTest(kind=card["kind"], chart=card["chart"]):
                result = compute(report, index, self.admin, today=TODAY)
                self.assertEqual(result["version"], 1)
                data = result["data"]
                if card["chart"] == "table":
                    self.assertEqual(result["shape"], "table")
                    self.assertGreater(len(data["columns"]), 1)
                    if entry["family"] == "days":
                        self.assertEqual(len(data["rows"]), report.range_days)
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


class CostProjectTestCase(ReportTestCase):
    """A priced project: a point is 100.00 (25.00 an hour, 4 hours to a point)."""

    def setUp(self):
        super().setUp()
        self.admin = make_user("coral", "admin")
        CostSettings.objects.create(pk=1, default_hours_per_point="4.00")
        PersonRate.objects.create(
            user=self.agent, hourly_wage=Decimal("25.00"), sprint_hours=Decimal("40.0")
        )
        self.project = service.create_project(self.admin, "NET", "Field Networking", "scrum")
        self.done = self.project.columns.get(category="done")

    def finished_issue(self, points, assignee=None, sprint=None):
        """Done work by *assignee*; its cost freezes as it lands in the column."""
        issue = service.create_issue(
            self.admin,
            self.project,
            title=f"{points} points of work",
            assignee=self.agent if assignee is None else assignee,
            story_points=points,
            sprint=sprint,
        )
        return service.move_issue(self.admin, issue, self.done)


class CostCardsTests(CostProjectTestCase):
    def test_cost_by_project_sums_done_work(self):
        self.finished_issue(2)
        self.finished_issue(1)

        report = self.report([{"kind": "cost_by_project", "chart": "table"}], owner=self.admin)
        data = compute(report, 0, self.admin, today=TODAY)["data"]
        self.assertEqual(data["columns"], ["Project", "Spent"])
        self.assertEqual(data["rows"], [["NET", "300.00"]])

    def test_cost_cards_hidden_without_permission(self):
        self.finished_issue(3)
        report = self.report([{"kind": "cost_by_project", "chart": "table"}], owner=self.admin)
        self.assertFalse(can_see_cost(self.agent))

        hidden = compute(report, 0, self.agent, today=TODAY)
        self.assertEqual(hidden["shape"], "stat")
        self.assertEqual(hidden["data"]["label"], "Cost hidden")

        CostSettings.objects.filter(pk=1).update(show_cost_totals_to_agents=True)
        data = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(data["rows"], [["NET", "300.00"]])

    def test_cost_per_point_admin_only(self):
        self.finished_issue(3)
        report = self.report([{"kind": "cost_per_point", "chart": "table"}], owner=self.admin)
        CostSettings.objects.filter(pk=1).update(show_cost_totals_to_agents=True)

        hidden = compute(report, 0, self.agent, today=TODAY)
        self.assertEqual(hidden["data"]["label"], "Cost hidden")

        data = compute(report, 0, self.admin, today=TODAY)["data"]
        self.assertEqual(data["columns"], ["Person", "Cost per point"])
        self.assertEqual(data["rows"], [["agent", "100.00"]])


class ProjectsGroupsTests(CostProjectTestCase):
    def test_velocity_shows_the_first_project_by_key(self):
        # Nothing is closed yet, so the card shows its empty series. Naming a
        # project earlier in the alphabet changes which project is asked.
        report = self.report([{"kind": "velocity"}], owner=self.admin)
        data = compute(report, 0, self.admin, today=TODAY)["data"]
        self.assertEqual(data["labels"], [])
        self.assertEqual([s["name"] for s in data["series"]], ["Committed", "Completed"])

        Sprint.objects.create(project=self.project, name="NET sprint", state="closed")
        service.create_project(self.admin, "ABC", "Alphabetical first", "scrum")
        data = compute(report, 0, self.admin, today=TODAY)["data"]
        self.assertEqual(data["labels"], [])

    def test_velocity_chart_of_the_first_project_by_key(self):
        sprint = Sprint.objects.create(project=self.project, name="Sprint 1", state="planned")
        service.start_sprint(self.admin, sprint, TODAY - timedelta(days=7), TODAY)
        self.finished_issue(3, sprint=sprint)
        service.complete_sprint(self.admin, sprint)

        # Committed counts what was in scope when the sprint began; this work
        # was finished after that, so only Completed sees it.
        report = self.report([{"kind": "velocity", "chart": "table"}], owner=self.admin)
        rows = compute(report, 0, self.admin, today=TODAY)["data"]["rows"]
        self.assertEqual(rows, [["Sprint 1", 0, 3]])

        service.create_project(self.admin, "ABC", "Alphabetical first", "scrum")
        data = compute(report, 0, self.admin, today=TODAY)["data"]
        self.assertEqual(data["columns"], ["Sprint", "Committed", "Completed"])
        self.assertEqual(data["rows"], [])

    def test_burndown_uses_the_active_sprint_of_the_first_project(self):
        first = service.create_project(self.admin, "AAA", "Nothing in it", "scrum")
        Sprint.objects.create(
            project=first,
            name="AAA sprint",
            state="active",
            start_date=TODAY - timedelta(days=2),
            end_date=TODAY + timedelta(days=5),
        )

        report = self.report([{"kind": "burndown"}], owner=self.admin)
        data = compute(report, 0, self.agent, today=TODAY)["data"]
        # AAA sorts before NET, so its sprint is the one that burns down.
        self.assertEqual(data["labels"][0], (TODAY - timedelta(days=2)).isoformat())
        self.assertEqual([s["name"] for s in data["series"]], ["Remaining", "Ideal"])

    def test_projects_cards_without_a_project_are_empty_not_wrong(self):
        CostSettings.objects.filter(pk=1).update(show_cost_totals_to_agents=True)
        report = self.report([{"kind": "velocity"}, {"kind": "burndown"}], projects=[self.project])
        report.projects.clear()
        for index, series in enumerate([["Committed", "Completed"], ["Remaining", "Ideal"]]):
            with self.subTest(index=index):
                data = compute(report, index, self.agent, today=TODAY)["data"]
                self.assertEqual(data["labels"], [])
                self.assertEqual([s["name"] for s in data["series"]], series)


class WikiTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.space = Space.objects.create(name="Reports")

    def page(self, title, **kwargs):
        """A page and its first save, both put down on the day asked."""
        created_at = kwargs.pop("created_at", self.now)
        page = Page.objects.create(space=self.space, title=title, created_at=created_at, **kwargs)
        PageVersion.objects.create(
            page=page, number=1, title=title, body=page.body, created_at=created_at
        )
        return page

    def edit(self, page, body, created_at=None):
        """A later save of the page — an edit, counted on its own day."""
        number = page.versions.order_by("-number").first().number + 1
        return PageVersion.objects.create(
            page=page,
            number=number,
            title=page.title,
            body=body,
            created_at=created_at or self.now,
        )

    def test_wiki_activity_counts_created_and_edited_pages(self):
        report = self.report([{"kind": "wiki_activity"}])
        before = compute(report, 0, self.agent, today=TODAY)["data"]
        created_before = sum(before["series"][0]["values"])
        edited_before = sum(before["series"][1]["values"])

        page = self.page("Deploying the relay", body="v1")
        # An earlier day's edit sits outside the window: it must not be counted.
        self.edit(page, "v2", created_at=self.now - timedelta(days=40))

        after = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual([s["name"] for s in after["series"]], ["Created", "Edited"])
        # The first save of a page is not an edit; the one after it is.
        self.assertEqual(sum(after["series"][1]["values"]), edited_before)
        self.assertEqual(sum(after["series"][0]["values"]), created_before + 1)
        self.assertEqual(after["series"][0]["values"][-1], created_before + 1)

    def test_wiki_activity_counts_a_later_save_of_a_page(self):
        report = self.report([{"kind": "wiki_activity"}])
        before = compute(report, 0, self.agent, today=TODAY)["data"]
        edited_before = sum(before["series"][1]["values"])

        page = self.page("Deploying the relay", body="v1")
        self.edit(page, "v2")

        after = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(sum(after["series"][1]["values"]), edited_before + 1)

    def test_wiki_activity_leaves_out_what_happened_before_the_window(self):
        long_ago = self.now - timedelta(days=40)
        self.page("An old page", body="v1", created_at=long_ago)
        report = self.report([{"kind": "wiki_activity"}])
        data = compute(report, 0, self.agent, today=TODAY)["data"]
        self.assertEqual(sum(data["series"][0]["values"]), 0)
        self.assertEqual(sum(data["series"][1]["values"]), 0)

    def test_wiki_top_pages_lists_the_most_read(self):
        quiet = self.page("Quiet page", views=1)
        busy = self.page("Busy page", views=9)

        report = self.report([{"kind": "wiki_top_pages", "chart": "table"}])
        rows = compute(report, 0, self.agent, today=TODAY)["data"]["rows"]
        self.assertEqual(rows[0], [busy.title, 9])
        self.assertIn([quiet.title, 1], rows)


class CsvTests(ReportTestCase):
    def test_csv_has_a_header_and_one_row_per_label(self):
        self.dated_ticket(self.now, title="today")

        report = self.report([{"kind": "ticket_volume"}])
        lines = list(csv.reader(csv_for(report, 0, self.agent, today=TODAY).splitlines()))
        self.assertEqual(lines[0], ["Day", "Created", "Resolved"])
        self.assertEqual(len(lines), 1 + report.range_days)
        self.assertEqual(lines[-1], [TODAY.isoformat(), "1", "0"])

        staff = list(staff_users())
        rows = self.report([{"kind": "agent_load", "chart": "table"}])
        lines = list(csv.reader(csv_for(rows, 0, self.agent, today=TODAY).splitlines()))
        self.assertEqual(lines[0], ["Agent", "Open tickets"])
        self.assertEqual(len(lines), 1 + len(staff))

    def test_csv_of_a_hidden_cost_card(self):
        report = self.report([{"kind": "cost_by_project"}])
        lines = list(csv.reader(csv_for(report, 0, self.agent, today=TODAY).splitlines()))
        self.assertEqual(lines, [["Value"], ["Cost hidden"]])


class ValidateReportTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("coral", "admin")

    def payload(self, **overrides):
        payload = {
            "name": "Weekly support",
            "description": "How the week went",
            "shared": True,
            "range_days": 30,
            "departments": [],
            "projects": [],
            "saved_views": [],
            "widgets": [
                {"kind": "ticket_volume", "chart": "line", "x": 0, "y": 0, "w": 6, "h": 4},
                {"kind": "status_mix", "chart": "table", "x": 6, "y": 0, "w": 6, "h": 4},
            ],
        }
        payload.update(overrides)
        return payload

    def test_validate_report_accepts_a_good_payload(self):
        self.assertEqual(validate_report(self.payload(), self.agent), [])

    def test_validate_refuses_unknown_kind_bad_chart_bad_size_and_out_of_range(self):
        errors = validate_report(
            self.payload(name="  ", range_days=8, widgets=[{"kind": "nope"}]), self.agent
        )
        self.assertIn("Give the report a name.", errors)
        self.assertIn("Pick a range of 7, 14, 30, 90, 180 or 365 days.", errors)
        self.assertIn("Card 1: unknown kind.", errors)

        errors = validate_report(
            self.payload(
                name="n" * 121,
                widgets=[
                    {"kind": "ticket_volume", "chart": "pie"},
                    {"kind": "csat", "title": "t" * 81, "x": 8, "w": 6},
                    {"kind": "agent_load", "w": 3, "h": 40},
                ],
            ),
            self.agent,
        )
        self.assertIn("Names are at most 120 characters.", errors)
        self.assertIn("Card 1: that chart does not suit this card.", errors)
        self.assertIn("Card 2: titles are at most 80 characters.", errors)
        self.assertIn("Card 2: it runs off the right of the grid.", errors)
        self.assertIn("Card 3: width is 1 to 12 and height 1 to 24.", errors)

        too_many = validate_report(
            self.payload(widgets=[{"kind": "ticket_volume"}] * 13), self.agent
        )
        self.assertEqual(too_many, ["A report holds at most 12 cards."])

    def test_validate_refuses_cost_cards_for_agents_and_foreign_saved_views(self):
        errors = validate_report(
            self.payload(widgets=[{"kind": "cost_by_project"}, {"kind": "cost_per_point"}]),
            self.agent,
        )
        self.assertIn("Card 1: you can't add cost cards.", errors)
        self.assertIn("Card 2: only admins can add cost-per-point cards.", errors)
        self.assertEqual(
            validate_report(self.payload(widgets=[{"kind": "cost_by_project"}]), self.admin), []
        )

        mine = SavedView.objects.create(owner=self.agent, query="status=open")
        theirs_shared = SavedView.objects.create(
            owner=self.colleague, query="status=open", is_shared=True
        )
        theirs_private = SavedView.objects.create(owner=self.colleague, query="status=open")
        # Shared with you or your own: nothing to refuse. Saving a private view
        # of someone else's would be lending them your filters, so it is refused.
        usable = validate_report(self.payload(saved_views=[mine.pk, theirs_shared.pk]), self.agent)
        self.assertEqual(usable, [])

        errors = validate_report(self.payload(saved_views=[theirs_private.pk]), self.agent)
        self.assertEqual(errors, ["A saved view in the sources is not yours to use."])

    def test_validate_refuses_sources_that_do_not_exist(self):
        sales = Department.objects.create(name="Sales")
        project = service.create_project(self.admin, "NET", "Field Networking", "scrum")
        self.assertEqual(
            validate_report(
                self.payload(departments=[sales.pk], projects=[project.pk]), self.admin
            ),
            [],
        )
        errors = validate_report(self.payload(departments=[sales.pk + 9999]), self.agent)
        self.assertEqual(
            errors, ["A department, project or saved view in the sources does not exist."]
        )


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

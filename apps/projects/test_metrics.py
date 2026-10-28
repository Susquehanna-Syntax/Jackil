"""The metrics: burndown, velocity, cumulative flow and the cost breakdown table."""

from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.dashboards.contract import validate_payload
from apps.projects import metrics, service
from apps.projects.models import CostSettings, Issue, IssueEvent, PersonRate, Sprint
from apps.projects.test_backlog import BacklogTest, make_user

START = date(2026, 3, 2)
END = date(2026, 3, 6)
TODAY = date(2026, 3, 10)
TZ = timezone.get_current_timezone()


def moment(day, hour=12):
    """A past instant, for an event or a sprint date the test wants in history."""
    return timezone.make_aware(datetime(day.year, day.month, day.day, hour), TZ)


class MetricsTest(BacklogTest):
    def setUp(self):
        super().setUp()
        self.waged = make_user("wren", "agent")
        PersonRate.objects.create(
            user=self.waged, hourly_wage=Decimal("25.00"), sprint_hours=Decimal("40.0")
        )

    def dated_sprint(self, name="Dated sprint", **fields):
        fields.setdefault("start_date", START)
        fields.setdefault("end_date", END)
        return self.sprint(name, **fields)

    def on_day(self, issue, kind, day, hour=12):
        """Send this issue's newest event of this kind back to a day in the past.

        The service stamps events with the current time; ``hour`` orders two
        events placed on the same day.
        """
        newest = IssueEvent.objects.filter(issue=issue, kind=kind).order_by("-id").first()
        IssueEvent.objects.filter(pk=newest.pk).update(created_at=moment(day, hour))
        return newest

    def joined_on(self, issue, sprint, day):
        """Put an issue in a sprint first thing on that day."""
        service.set_sprint(self.admin, issue, sprint)
        self.on_day(issue, "sprint_added", day, hour=1)

    def started_on(self, sprint, when):
        Sprint.objects.filter(pk=sprint.pk).update(
            state="active", start_date=when.date(), started_at=when
        )

    def finish(self, sprint, issues, day, hour=11):
        """Finish work on ``day`` and close the sprint at the end of it.

        The service's own close stamps today and would refuse later changes.
        """
        for issue in issues:
            service.move_issue(self.admin, issue, self.done)
            Issue.objects.filter(pk=issue.pk).update(completed_at=moment(day, hour))
        Sprint.objects.filter(pk=sprint.pk).update(state="closed", closed_at=moment(day, 23))

    def remaining(self, payload):
        return self.values(payload)["Remaining"]

    def values(self, payload):
        return {item["name"]: item["values"] for item in payload["series"]}


class BurndownTests(MetricsTest):
    """One eight-point story in a five-day sprint, plus each change to it."""

    def setUp(self):
        super().setUp()
        self.kickoff = self.dated_sprint()
        self.story = self.issue(title="Story one", assignee=self.waged, story_points=8)
        self.joined_on(self.story, self.kickoff, START)

    def test_burndown_ideal_line_and_remaining_drop_on_done(self):
        service.move_issue(self.admin, self.story, self.done)
        self.on_day(self.story, "moved", date(2026, 3, 4))

        payload = metrics.burndown(self.kickoff, today=END)

        self.assertEqual(payload["kind"], "line")
        self.assertEqual(
            payload["labels"],
            ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"],
        )
        series = self.values(payload)
        self.assertEqual(series["Remaining"], [8, 8, 0, 0, 0])
        self.assertEqual(series["Ideal"], [8, 6, 4, 2, 0])

    def test_burndown_scope_added_mid_sprint_steps_up(self):
        late = self.issue(title="Later in", assignee=self.waged, story_points=5)
        service.set_sprint(self.admin, late, self.kickoff)
        self.on_day(late, "sprint_added", date(2026, 3, 4))

        self.assertEqual(
            self.remaining(metrics.burndown(self.kickoff, today=END)), [8, 8, 13, 13, 13]
        )

    def test_burndown_points_change_mid_sprint(self):
        # Re-estimated from eight to three on the 4th: the days before keep the
        # size carried then.
        service.set_points(self.admin, self.story, 3)
        self.on_day(self.story, "points", date(2026, 3, 4))

        self.assertEqual(self.remaining(metrics.burndown(self.kickoff, today=END)), [8, 8, 3, 3, 3])

    def test_burndown_ignores_an_issue_moved_to_another_sprint(self):
        carried_into = self.sprint("Next sprint")
        service.set_sprint(self.admin, self.story, carried_into)
        self.on_day(self.story, "sprint_added", date(2026, 3, 4))

        self.assertEqual(self.remaining(metrics.burndown(self.kickoff, today=END)), [8, 8, 0, 0, 0])

    def test_burndown_without_a_start_date_is_empty(self):
        unscheduled = self.sprint("No dates")
        service.set_sprint(self.admin, self.story, unscheduled)

        payload = metrics.burndown(unscheduled, today=END)

        self.assertEqual(payload["labels"], [])
        for item in payload["series"]:
            self.assertEqual(item["values"], [])

    def test_burndown_excludes_a_sub_task_of_a_sprint_story(self):
        """Sub-tasks ride with their story's card and carry no points here."""
        service.create_issue(
            self.admin,
            self.project,
            title="Its sub-task",
            type="subtask",
            parent=self.story,
            story_points=4,
        )

        self.assertEqual(self.remaining(metrics.burndown(self.kickoff, today=END)), [8, 8, 8, 8, 8])


class VelocityTests(MetricsTest):
    """What a sprint took on at its start, against what it finished by its close."""

    def test_velocity_committed_vs_completed(self):
        first = self.sprint("First")
        kept = self.in_sprint(first, "Kept", 5, START)
        dropped = self.in_sprint(first, "Dropped", 3, START)
        late = self.in_sprint(first, "Late work", 2, START)
        self.started_on(first, moment(START, 13))
        # Dropped on the 4th: committed at the start, never completed.
        service.set_sprint(self.admin, dropped, None)
        self.on_day(dropped, "sprint_removed", date(2026, 3, 4))
        self.finish(first, [kept, late], END)

        second = self.sprint("Second")
        self.in_sprint(second, "Carried over", 4, date(2026, 3, 7))
        self.started_on(second, moment(date(2026, 3, 7), 13))
        self.finish(second, [], date(2026, 3, 8))

        payload = metrics.velocity_chart(self.project)

        self.assertEqual(payload["kind"], "bar")
        self.assertEqual(payload["labels"], ["First", "Second"])
        series = self.values(payload)
        self.assertEqual(series["Committed"], [10, 4])
        self.assertEqual(series["Completed"], [7, 0])

    def in_sprint(self, sprint, title, points, day):
        story = self.issue(title=title, assignee=self.waged, story_points=points)
        service.set_sprint(self.admin, story, sprint)
        self.on_day(story, "sprint_added", day)
        return story


class CumulativeFlowTests(MetricsTest):
    def test_cumulative_flow_counts_per_category_per_day(self):
        old = self.issue(title="Old story", assignee=self.waged, story_points=1)
        self.on_day(old, "created", date(2026, 3, 7))

        later = self.issue(title="Later story", assignee=self.waged, story_points=1)
        self.on_day(later, "created", date(2026, 3, 8))
        service.move_issue(self.admin, later, self.doing)
        self.on_day(later, "moved", date(2026, 3, 9))

        child = service.create_issue(
            self.admin, self.project, title="A sub-task", type="subtask", parent=later
        )
        self.on_day(child, "created", date(2026, 3, 8))

        payload = metrics.cumulative_flow(self.project, days=4, today=TODAY)

        self.assertEqual(payload["kind"], "line")
        self.assertEqual(
            payload["labels"], ["2026-03-07", "2026-03-08", "2026-03-09", "2026-03-10"]
        )
        self.assertEqual(
            [item["name"] for item in payload["series"]], ["To do", "In progress", "Done"]
        )
        series = self.values(payload)
        self.assertEqual(series["To do"], [1, 2, 1, 1])
        self.assertEqual(series["In progress"], [0, 0, 1, 1])
        self.assertEqual(series["Done"], [0, 0, 0, 0])


class PayloadTests(MetricsTest):
    """Every metric must return a payload the widget contract accepts."""

    def test_every_metric_is_a_valid_contract_payload(self):
        sprint = self.dated_sprint("Payload sprint")
        story = self.issue(title="Payload story", assignee=self.waged, story_points=3)
        service.set_sprint(self.admin, story, sprint)
        service.move_issue(self.admin, story, self.done)

        validate_payload("series", metrics.burndown(sprint, today=END))
        validate_payload("series", metrics.velocity_chart(self.project))
        validate_payload("series", metrics.cumulative_flow(self.project, days=3, today=END))
        # Rows come out of an empty project too: the epic table still names the
        # work with no epic above it.
        self.issue(title="Payload cost", assignee=self.waged, story_points=2)
        for by in ("person", "epic", "sprint"):
            validate_payload("table", metrics.cost_breakdown(self.project, by, self.admin))


GROUP_COLUMNS = ["Name", "Points done", "Cost", "Planned cost", "Issues left out"]
PERSON_COLUMNS = ["Person", "Points done", "Cost", "Cost per point", "Issues left out"]


class CostBreakdownTests(MetricsTest):
    def setUp(self):
        super().setUp()
        self.rateless = make_user("rateless", "agent")
        CostSettings.objects.filter(pk=1).update(show_cost_totals_to_agents=True)

    def priced(self, title, points, parent=None, sprint=None):
        """A story with a price on it: wren's worth and the org's hours a point."""
        story = self.issue(title=title, assignee=self.waged, story_points=points, parent=parent)
        if sprint is not None:
            service.set_sprint(self.admin, story, sprint)
        return story

    def rows(self, by, name, user=None):
        """The named row of one grouping, whatever else the table holds."""
        payload = metrics.cost_breakdown(self.project, by, user or self.admin)
        expected = PERSON_COLUMNS if by == "person" else GROUP_COLUMNS
        self.assertEqual(payload["columns"], expected)
        return next(row for row in payload["rows"] if row[0] == name)

    def test_cost_breakdown_by_epic_and_sprint(self):
        epic = self.issue(title="Mail move", type="epic")
        sprint = self.sprint("Sprint one")
        under = self.priced("Under the epic", 3, parent=epic, sprint=sprint)
        self.priced("Still open", 2, parent=epic)
        loose = self.priced("No epic above", 5)
        service.move_issue(self.admin, under, self.done)
        service.move_issue(self.admin, loose, self.done)

        # Planned cost counts every issue in the group, done or not.
        self.assertEqual(self.rows("epic", "Mail move"), ["Mail move", 3, "300.00", "500.00", 0])
        self.assertEqual(self.rows("epic", "No epic"), ["No epic", 5, "500.00", "500.00", 0])
        self.assertEqual(
            self.rows("sprint", "Sprint one"), ["Sprint one", 3, "300.00", "300.00", 0]
        )
        self.assertEqual(self.rows("sprint", "Backlog"), ["Backlog", 5, "500.00", "700.00", 0])
        self.assertEqual(self.rows("person", "wren"), ["wren", 8, "800.00", "100.00", 0])

    def test_cost_per_point_with_no_points_done_is_a_dash(self):
        story = self.issue(title="Finished with no points", assignee=self.waged)
        service.move_issue(self.admin, story, self.done)
        story.refresh_from_db()
        self.assertIsNone(story.frozen_cost)

        self.assertEqual(self.rows("person", "wren"), ["wren", 0, "0.00", "—", 1])

    def test_left_out_issues_are_counted(self):
        """A done issue nobody can price is counted, not silently dropped."""
        finished = self.issue(title="Who pays for this", assignee=self.rateless, story_points=3)
        service.move_issue(self.admin, finished, self.done)

        self.assertEqual(self.rows("person", "rateless"), ["rateless", 3, "0.00", "0.00", 1])
        self.assertEqual(self.rows("epic", "No epic"), ["No epic", 3, "0.00", "0.00", 1])

    def test_cost_breakdown_permissions(self):
        CostSettings.objects.filter(pk=1).update(show_cost_totals_to_agents=False)
        for by in ("person", "epic", "sprint"):
            with self.assertRaises(PermissionDenied):
                metrics.cost_breakdown(self.project, by, self.agent)

        CostSettings.objects.filter(pk=1).update(show_cost_totals_to_agents=True)
        metrics.cost_breakdown(self.project, "epic", self.agent)
        metrics.cost_breakdown(self.project, "sprint", self.agent)
        with self.assertRaises(PermissionDenied):
            metrics.cost_breakdown(self.project, "person", self.agent)
        for by in ("person", "epic", "sprint"):
            metrics.cost_breakdown(self.project, by, self.admin)

        with self.assertRaises(ValueError):
            metrics.cost_breakdown(self.project, "bogus", self.admin)

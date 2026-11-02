"""The cost estimate: velocity, hours per point, freezing, and totals.

Every missing input must produce a ``None`` or the org default — never a
crash and never a float.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.projects import cost, service
from apps.projects.models import CostSettings, Issue, PersonRate, Sprint


def make_user(username):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role="agent")


class CostTestCase(TestCase):
    """A project, a default-having CostSettings, and a sprint factory."""

    def setUp(self):
        self.admin = User.objects.create_user("coral", "c@x.com", "pw", role="admin")
        CostSettings.objects.create(pk=1, default_hours_per_point="4.00")
        self.project = service.create_project(self.admin, "NET", "Networking", "scrum")
        self.todo = self.project.columns.get(category="todo")
        self.done = self.project.columns.get(category="done")
        self.clock = timezone.now()
        self.day = 0

    def closed_sprint(self, name, points_by=None, offset_days=30):
        """A closed sprint with `points_by` = {user: points} completed inside it.

        The completed work is stamped by hand: a closed sprint refuses new
        work through the service, and these sprints are history already.
        """
        started = self.clock + timedelta(days=offset_days)
        sprint = Sprint.objects.create(
            project=self.project,
            name=name,
            state="closed",
            started_at=started,
            closed_at=started + timedelta(days=1),
        )
        for user, points in (points_by or {}).items():
            self.complete(sprint, user, points, at=started + timedelta(hours=1))
        return sprint

    def complete(self, sprint, user, points, at=None):
        """An issue assigned to `user`, done inside `sprint`'s window."""
        issue = service.create_issue(
            self.admin, self.project, title=f"{user.username} work", assignee=user
        )
        service.set_points(self.admin, issue, points)
        issue.sprint = sprint
        issue.column = self.done
        issue.completed_by = user
        issue.completed_at = at or sprint.started_at + timedelta(hours=12)
        issue.save()
        return issue


class VelocityTests(CostTestCase):
    def test_velocity_needs_three_sprints_of_history(self):
        aria = make_user("aria")
        self.assertIsNone(cost.velocity(aria))

        self.closed_sprint("S1", {aria: 10})
        self.assertIsNone(cost.velocity(aria))
        self.closed_sprint("S2", {aria: 20})
        self.assertIsNone(cost.velocity(aria))

        self.closed_sprint("S3", {aria: 30})
        self.assertEqual(cost.velocity(aria), Decimal("20"))

    def test_velocity_averages_only_the_last_three_sprints(self):
        aria = make_user("aria")
        self.closed_sprint("S1", {aria: 90}, offset_days=10)
        self.closed_sprint("S2", {aria: 3}, offset_days=20)
        self.closed_sprint("S3", {aria: 6}, offset_days=30)
        self.closed_sprint("S4", {aria: 9}, offset_days=40)
        self.assertEqual(cost.velocity(aria), Decimal("6"))

    def test_velocity_counts_only_that_persons_completed_work(self):
        aria = make_user("aria")
        boa = make_user("boa")
        for name in ("S1", "S2", "S3"):
            self.closed_sprint(name, {aria: 10, boa: 40})
        self.assertEqual(cost.velocity(aria), Decimal("10"))
        self.assertEqual(cost.velocity(boa), Decimal("40"))

    def test_velocity_ignores_work_outside_the_sprints_window(self):
        aria = make_user("aria")
        s1 = self.closed_sprint("S1", {aria: 10})
        self.closed_sprint("S2", {aria: 10})
        self.closed_sprint("S3", {aria: 10})
        stray = service.create_issue(self.admin, self.project, title="Late", assignee=aria)
        service.set_points(self.admin, stray, 8)
        stray.sprint = s1
        stray.column = self.done
        stray.completed_by = aria
        stray.completed_at = s1.closed_at + timedelta(days=2)
        stray.save()
        self.assertEqual(cost.velocity(aria), Decimal("10"))

    def test_velocity_scope_and_as_of(self):
        aria = make_user("aria")
        for name in ("S1", "S2", "S3"):
            self.closed_sprint(name, {aria: 12})
        self.assertEqual(cost.velocity(aria, project=self.project), Decimal("12"))
        other = service.create_project(self.admin, "SVC", "Services", "scrum")
        self.assertIsNone(cost.velocity(aria, project=other))
        self.assertIsNone(cost.velocity(aria, as_of=self.clock - timedelta(days=365)))


class HoursPerPointTests(CostTestCase):
    def test_hours_per_point_from_velocity(self):
        aria = make_user("aria")
        PersonRate.objects.create(user=aria, hourly_wage="45.00", sprint_hours=Decimal("40.0"))
        for name in ("S1", "S2", "S3"):
            self.closed_sprint(name, {aria: 20})
        self.assertEqual(cost.hours_per_point(aria), Decimal("2.000"))

    def test_hours_per_point_falls_back_to_default_without_history(self):
        # No 3-sprint history: hours per point is the admin's org-wide default.
        aria = make_user("aria")
        PersonRate.objects.create(user=aria, hourly_wage="45.00", sprint_hours=Decimal("40.0"))
        self.assertEqual(cost.hours_per_point(aria), Decimal("4.00"))

    def test_zero_velocity_falls_back_to_default(self):
        aria = make_user("aria")
        PersonRate.objects.create(user=aria, hourly_wage="45.00", sprint_hours=Decimal("40.0"))
        for name in ("S1", "S2", "S3"):
            self.closed_sprint(name, {aria: 0})
        self.assertEqual(cost.hours_per_point(aria), Decimal("4.00"))

    def test_hours_per_point_without_sprint_hours_uses_default(self):
        aria = make_user("aria")
        PersonRate.objects.create(user=aria, hourly_wage="45.00")
        for name in ("S1", "S2", "S3"):
            self.closed_sprint(name, {aria: 20})
        self.assertEqual(cost.hours_per_point(aria), Decimal("4.00"))

    def test_hours_per_point_without_history_is_the_org_default(self):
        # The admin's default is what a person without history is priced at,
        # whether or not their sprint hours are set.
        nobody = make_user("nobody")
        self.assertEqual(cost.hours_per_point(nobody), Decimal("4.00"))
        PersonRate.objects.create(user=nobody, hourly_wage="45.00")
        self.assertEqual(cost.hours_per_point(nobody), Decimal("4.00"))
        PersonRate.objects.filter(user=nobody).update(sprint_hours=Decimal("40.0"))
        self.assertEqual(cost.hours_per_point(nobody), Decimal("4.00"))


class IssueCostTests(CostTestCase):
    def setUp(self):
        super().setUp()
        self.aria = make_user("aria")
        PersonRate.objects.create(user=self.aria, hourly_wage="45.00")
        # 3 closed sprints of 20 completed points each with 40 sprint hours
        # set: velocity 20, hours per point 2.000, so 5 points is $450.00.
        for name in ("S1", "S2", "S3"):
            self.closed_sprint(name, {self.aria: 20})
        PersonRate.objects.filter(user=self.aria).update(sprint_hours=Decimal("40.0"))

    def test_issue_cost_live_estimate(self):
        issue = service.create_issue(
            self.admin,
            self.project,
            title="Patch panel",
            assignee=self.aria,
            story_points=5,
        )
        self.assertEqual(cost.issue_cost(issue), Decimal("450.00"))

    def test_issue_cost_is_none_without_points_assignee_or_wage(self):
        unpointed = service.create_issue(
            self.admin, self.project, title="Triage", assignee=self.aria
        )
        self.assertIsNone(cost.issue_cost(unpointed))

        unassigned = service.create_issue(self.admin, self.project, title="Triage", story_points=3)
        self.assertIsNone(cost.issue_cost(unassigned))

        nobody = make_user("boa")
        unpaid = service.create_issue(
            self.admin, self.project, title="Triage", assignee=nobody, story_points=3
        )
        self.assertIsNone(cost.issue_cost(unpaid))

    def test_frozen_cost_survives_a_wage_change(self):
        issue = service.create_issue(
            self.admin,
            self.project,
            title="Patch panel",
            assignee=self.aria,
            story_points=5,
        )
        service.move_issue(self.admin, issue, self.done)
        issue.refresh_from_db()
        self.assertEqual(issue.frozen_cost, Decimal("450.00"))
        self.assertEqual(issue.frozen_hours_per_point, Decimal("2.000"))

        PersonRate.objects.filter(user=self.aria).update(hourly_wage="90.00")
        issue.refresh_from_db()
        self.assertEqual(cost.issue_cost(issue), Decimal("450.00"))

    def test_reassigning_a_done_issue_keeps_its_frozen_cost(self):
        issue = service.create_issue(
            self.admin,
            self.project,
            title="Patch panel",
            assignee=self.aria,
            story_points=5,
        )
        service.move_issue(self.admin, issue, self.done)
        boa = make_user("boa")
        PersonRate.objects.create(user=boa, hourly_wage="99.00", sprint_hours=Decimal("40.0"))

        issue.assignee = boa
        issue.save(update_fields=["assignee"])
        issue.refresh_from_db()
        self.assertEqual(issue.completed_by, self.aria)
        self.assertEqual(cost.issue_cost(issue), Decimal("450.00"))

    def test_reopened_issue_cost_is_live_again(self):
        issue = service.create_issue(
            self.admin,
            self.project,
            title="Patch panel",
            assignee=self.aria,
            story_points=5,
        )
        service.move_issue(self.admin, issue, self.done)
        PersonRate.objects.filter(user=self.aria).update(hourly_wage="10.00")

        in_progress = self.project.columns.get(category="in_progress")
        service.move_issue(self.admin, issue, in_progress)
        issue.refresh_from_db()
        self.assertIsNone(issue.frozen_cost)
        self.assertEqual(cost.issue_cost(issue), Decimal("100.00"))

    def test_freeze_leaves_cost_none_when_there_is_nothing_to_price(self):
        issue = service.create_issue(self.admin, self.project, title="Triage")
        service.move_issue(self.admin, issue, self.done)
        issue.refresh_from_db()
        self.assertIsNotNone(issue.completed_at)
        self.assertIsNone(issue.completed_by)
        self.assertIsNone(issue.frozen_cost)
        self.assertIsNone(issue.frozen_hours_per_point)

    def test_freeze_leaves_cost_none_when_the_assignee_has_no_wage(self):
        # "Not set" people contribute nothing to totals (the spec's rule).
        boa = make_user("boa")
        issue = service.create_issue(
            self.admin, self.project, title="Triage", assignee=boa, story_points=3
        )
        service.move_issue(self.admin, issue, self.done)
        issue.refresh_from_db()
        self.assertEqual(issue.completed_by, boa)
        self.assertIsNone(issue.frozen_cost)


class RollupAndTotalTests(CostTestCase):
    def setUp(self):
        super().setUp()
        self.aria = make_user("aria")
        PersonRate.objects.create(
            user=self.aria, hourly_wage=Decimal("45.00"), sprint_hours=Decimal("40.0")
        )

    def test_rollup_points_is_the_issues_own_value(self):
        epic = service.create_issue(self.admin, self.project, type="epic", title="Rewire IDF")
        story = service.create_issue(
            self.admin, self.project, type="story", title="Patch panel", parent=epic
        )
        child = service.create_issue(
            self.admin, self.project, type="subtask", title="Crimp jack", parent=story
        )
        service.set_points(self.admin, story, 8)
        self.assertEqual(cost.rollup_points(story), 8)
        self.assertEqual(cost.rollup_points(child), 0)
        self.assertEqual(cost.rollup_points(epic), 0)

    def test_total_cost_counts_the_left_out_issues(self):
        known = service.create_issue(
            self.admin,
            self.project,
            title="Patch panel",
            assignee=self.aria,
            story_points=5,
        )
        unpointed = service.create_issue(
            self.admin, self.project, title="Triage", assignee=self.aria
        )
        unassigned = service.create_issue(
            self.admin, self.project, title="Refurb switches", story_points=3
        )
        total, missing = cost.total_cost([known, unpointed, unassigned])
        self.assertEqual(total, Decimal("900.00"))
        self.assertEqual(missing, 2)

    def test_total_cost_of_nothing_is_zero_and_counts_nothing(self):
        self.assertEqual(cost.total_cost([]), (Decimal("0.00"), 0))

    def test_money_is_decimal_rounded_to_cents(self):
        # No float anywhere in the module (the acceptance grep).
        source = Path(cost.__file__).read_text(encoding="utf-8")
        self.assertNotIn("float(", source)

        # 5 points × 4.00 h/pt (the org default) × $45.00 = $900.00, and the
        # frozen figure below is a leftover fraction of a cent rounding half-up.
        issue = service.create_issue(
            self.admin,
            self.project,
            title="Patch panel",
            assignee=self.aria,
            story_points=5,
        )
        priced = cost.issue_cost(issue)
        self.assertIsInstance(priced, Decimal)
        self.assertEqual(priced, Decimal("900.00"))
        self.assertEqual(priced.as_tuple().exponent, -2)

        total, missing = cost.total_cost([issue])
        self.assertEqual(total, Decimal("900.00"))
        self.assertEqual(missing, 0)

    def test_money_quantises_a_velocity_derived_cost_to_cents(self):
        # 40.0 sprint hours over an average of 3 points per sprint is
        # 13.333… h/pt; 5 points at $45.00/h is $2999.999999999999999999999999,
        # which quantises half-up to $3000.00.
        penny = make_user("penny")
        PersonRate.objects.create(
            user=penny, hourly_wage=Decimal("45.00"), sprint_hours=Decimal("40.0")
        )
        for name in ("S1", "S2", "S3"):
            self.closed_sprint(name, {penny: 3})
        self.assertEqual(cost.velocity(penny), Decimal("3"))
        issue = service.create_issue(
            self.admin, self.project, title="Patch panel", assignee=penny, story_points=5
        )
        self.assertEqual(cost.issue_cost(issue), Decimal("3000.00"))

    def test_a_frozen_cost_is_read_at_whole_cents(self):
        issue = service.create_issue(
            self.admin,
            self.project,
            title="Patch panel",
            assignee=self.aria,
            story_points=1,
        )
        service.move_issue(self.admin, issue, self.done)
        Issue.objects.filter(pk=issue.pk).update(frozen_cost=Decimal("12.3450001"))
        issue.refresh_from_db()
        self.assertEqual(cost.issue_cost(issue), Decimal("12.35"))
        total, missing = cost.total_cost([issue])
        self.assertEqual(total, Decimal("12.35"))
        self.assertEqual(missing, 0)


class SprintWindowTests(CostTestCase):
    def test_completion_before_a_sprint_started_is_not_counted(self):
        aria = make_user("aria")
        s1 = self.closed_sprint("S1", {aria: 10})
        self.closed_sprint("S2", {aria: 10})
        self.closed_sprint("S3", {aria: 10})
        early = service.create_issue(self.admin, self.project, title="Early", assignee=aria)
        service.set_points(self.admin, early, 9)
        early.sprint = s1
        early.column = self.done
        early.completed_by = aria
        early.completed_at = s1.started_at - timedelta(days=1)
        early.save()
        self.assertEqual(cost.velocity(aria), Decimal("10"))

    def test_unplanned_sprint_counts_its_whole_life(self):
        aria = make_user("aria")
        unplanned = Sprint.objects.create(
            project=self.project,
            name="Hotfix",
            closed_at=self.clock + timedelta(days=1),
        )
        issue = self.complete(unplanned, aria, 5, at=self.clock)
        unplanned.state = "closed"
        unplanned.save(update_fields=["state"])
        self.closed_sprint("S2", {aria: 5})
        self.closed_sprint("S3", {aria: 5})
        self.assertEqual(issue.completed_at, self.clock)
        self.assertEqual(cost.velocity(aria), Decimal("5"))

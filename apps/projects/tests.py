"""Projects models and service: keys, numbering, parenting, sprints, events."""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.projects import service
from apps.projects.models import Column, CostSettings, PersonRate, Project, Sprint


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class ProjectModelTests(TestCase):
    def test_project_key_must_be_letters_and_digits(self):
        for bad in ["N", "1NET", "neT", "NET-1", "NET W", "ABCDEFGHIJK"]:
            with self.subTest(key=bad):
                with self.assertRaises(ValidationError):
                    Project(key=bad, name="Networking").clean()
        Project(key="NET", name="Networking").clean()
        Project(key="IT24", name="IT").clean()

    def test_create_project_is_admin_only_and_makes_three_columns(self):
        admin = make_user("coral", "admin")
        agent = make_user("aria", "agent")
        with self.assertRaises(PermissionDenied):
            service.create_project(agent, "NET", "Networking", "scrum")

        project = service.create_project(admin, "NET", "Networking", "scrum")
        self.assertEqual(
            [(c.name, c.category, c.order) for c in project.columns.all()],
            [("To do", "todo", 0), ("In progress", "in_progress", 1), ("Done", "done", 2)],
        )

        kanban = service.create_project(admin, "SVC", "Services", "kanban")
        self.assertEqual(
            [(c.name, c.category) for c in kanban.columns.all()],
            [("To do", "todo"), ("In progress", "in_progress"), ("Done", "done")],
        )

    def test_cost_settings_singleton_is_created_on_demand(self):
        solo = CostSettings.get_solo()
        self.assertEqual(solo.pk, 1)
        self.assertEqual(CostSettings.objects.count(), 1)
        self.assertEqual(CostSettings.get_solo().pk, solo.pk)


class IssueModelTests(TestCase):
    def setUp(self):
        self.admin = make_user("coral", "admin")
        self.agent = make_user("aria", "agent")
        self.project = service.create_project(self.admin, "NET", "Networking", "scrum")
        self.other = service.create_project(self.admin, "SVC", "Services", "kanban")

    def test_issue_numbers_count_up_per_project(self):
        first = service.create_issue(self.agent, self.project, title="VLAN trunk down")
        second = service.create_issue(self.agent, self.project, title="DHCP pool full")
        elsewhere = service.create_issue(self.agent, self.other, title="Switch RMA")
        self.assertEqual((first.number, second.number), (1, 2))
        self.assertEqual(elsewhere.number, 1)
        self.project.refresh_from_db()
        self.assertEqual(self.project.next_number, 3)

    def test_issue_key_is_project_key_dash_number(self):
        issue = service.create_issue(self.agent, self.project, title="VLAN trunk down")
        self.assertEqual(issue.key, "NET-1")

    def test_new_issue_lands_in_the_first_todo_column_at_the_bottom_of_rank(self):
        first = service.create_issue(self.agent, self.project, title="One")
        second = service.create_issue(self.agent, self.project, title="Two")
        todo = self.project.columns.get(category="todo")
        self.assertEqual(first.column, todo)
        self.assertEqual(second.column, todo)
        self.assertGreater(second.rank, first.rank)

    def test_create_issue_is_staff_only(self):
        customer = make_user("boa", "customer")
        with self.assertRaises(PermissionDenied):
            service.create_issue(customer, self.project, title="Nope")

    def test_parent_rules(self):
        epic = service.create_issue(self.agent, self.project, type="epic", title="Rewire IDF")
        story = service.create_issue(
            self.agent, self.project, type="story", title="Patch panel", parent=epic
        )
        self.assertEqual(story.parent, epic)

        with self.assertRaises(ValidationError):
            service.create_issue(self.agent, self.project, type="epic", title="Nested", parent=epic)

        subtask = service.create_issue(
            self.agent, self.project, type="subtask", title="Crimp jack", parent=story
        )
        self.assertEqual(subtask.parent, story)

        with self.assertRaises(ValidationError):
            service.create_issue(self.agent, self.project, type="subtask", title="Orphan")
        with self.assertRaises(ValidationError):
            service.create_issue(
                self.agent, self.project, type="subtask", title="Under epic", parent=epic
            )
        with self.assertRaises(ValidationError):
            service.create_issue(
                self.agent, self.project, type="story", title="Under story", parent=story
            )

        foreign_epic = service.create_issue(self.agent, self.other, type="epic", title="Other")
        with self.assertRaises(ValidationError):
            service.create_issue(
                self.agent, self.project, type="story", title="Cross-project", parent=foreign_epic
            )


class ColumnMoveTests(TestCase):
    def setUp(self):
        self.admin = make_user("coral", "admin")
        self.agent = make_user("aria", "agent")
        CostSettings.objects.create(
            pk=1, default_hours_per_point="4.00", show_cost_totals_to_agents=False
        )
        self.project = service.create_project(self.admin, "NET", "Networking", "scrum")
        self.todo = self.project.columns.get(category="todo")
        self.in_progress = self.project.columns.get(category="in_progress")
        self.done = self.project.columns.get(category="done")
        PersonRate.objects.create(
            user=self.agent, hourly_wage="45.00", sprint_hours=Decimal("40.0")
        )

    def test_moving_to_done_sets_completed_and_freezes(self):
        issue = service.create_issue(
            self.agent, self.project, title="Patch panel", story_points=5, assignee=self.agent
        )
        self.assertIsNone(issue.completed_at)

        service.move_issue(self.admin, issue, self.done)
        issue.refresh_from_db()
        self.assertIsNotNone(issue.completed_at)
        self.assertEqual(issue.completed_by, self.agent)
        # No history yet, so hours per point is the org default of 4.00.
        self.assertEqual(issue.frozen_hours_per_point, Decimal("4.000"))
        # frozen_hours_per_point carries the model's 3 decimals; 5 points at
        # 4.000 h and $45.00/h is $900.00.
        self.assertEqual(issue.frozen_cost, Decimal("900.00"))

    def test_moving_out_of_done_unfreezes(self):
        issue = service.create_issue(
            self.agent, self.project, title="Patch panel", story_points=5, assignee=self.agent
        )
        service.move_issue(self.agent, issue, self.done)
        issue.refresh_from_db()
        self.assertIsNotNone(issue.frozen_cost)

        service.move_issue(self.agent, issue, self.in_progress)
        issue.refresh_from_db()
        self.assertIsNone(issue.completed_at)
        self.assertIsNone(issue.completed_by)
        self.assertIsNone(issue.frozen_cost)
        self.assertIsNone(issue.frozen_hours_per_point)

    def test_moving_within_done_keeps_the_original_completion(self):
        issue = service.create_issue(
            self.agent, self.project, title="Patch panel", story_points=5, assignee=self.agent
        )
        service.move_issue(self.agent, issue, self.done)
        issue.refresh_from_db()
        completed_at = issue.completed_at

        second_done = Column.objects.create(project=self.project, name="Archived", category="done")
        service.move_issue(self.agent, issue, second_done)
        issue.refresh_from_db()
        self.assertEqual(issue.completed_at, completed_at)

    def test_moving_to_a_column_of_another_project_is_refused(self):
        other = service.create_project(self.admin, "SVC", "Services", "kanban")
        issue = service.create_issue(self.agent, self.project, title="Patch panel")
        with self.assertRaises(ValidationError):
            service.move_issue(self.agent, issue, other.columns.first())


class SprintTests(TestCase):
    def setUp(self):
        self.admin = make_user("coral", "admin")
        self.agent = make_user("aria", "agent")
        self.project = service.create_project(self.admin, "NET", "Networking", "scrum")
        self.sprint = Sprint.objects.create(project=self.project, name="Sprint 1")

    def test_subtasks_carry_no_points_and_follow_their_parent_into_a_sprint(self):
        epic = service.create_issue(self.agent, self.project, type="epic", title="Rewire IDF")
        story = service.create_issue(
            self.agent, self.project, type="story", title="Patch panel", parent=epic
        )
        child = service.create_issue(
            self.agent, self.project, type="subtask", title="Crimp jack", parent=story
        )

        with self.assertRaises(ValidationError) as ctx:
            service.set_points(self.agent, child, 3)
        self.assertEqual(
            str(ctx.exception.messages[0]),
            "Sub-tasks carry no points; they roll up into their parent.",
        )
        service.set_points(self.agent, story, 5)
        story.refresh_from_db()
        self.assertEqual(story.story_points, 5)

        service.set_sprint(self.agent, story, self.sprint)
        child.refresh_from_db()
        story.refresh_from_db()
        self.assertEqual(story.sprint, self.sprint)
        self.assertEqual(child.sprint, self.sprint)
        self.assertTrue(child.events.filter(kind="sprint_added").exists())

        with self.assertRaises(ValidationError):
            service.set_sprint(self.agent, child, self.sprint)

    def test_closed_sprints_refuse_new_issues(self):
        issue = service.create_issue(self.agent, self.project, title="Patch panel")
        closed = Sprint.objects.create(
            project=self.project, name="Sprint 0", state="closed", closed_at=timezone.now()
        )
        with self.assertRaises(ValidationError):
            service.set_sprint(self.agent, issue, closed)

    def test_only_one_active_sprint_per_project(self):
        second = Sprint.objects.create(project=self.project, name="Sprint 2")
        service.start_sprint(self.agent, self.sprint, "2026-11-02", "2026-11-13")
        self.sprint.refresh_from_db()
        self.assertEqual(self.sprint.state, "active")
        self.assertIsNotNone(self.sprint.started_at)

        with self.assertRaises(ValidationError):
            service.start_sprint(self.agent, second, "2026-11-16", "2026-11-27")

    def test_complete_sprint_moves_open_issues_to_the_backlog_or_next_sprint(self):
        done = self.project.columns.get(category="done")
        in_progress = self.project.columns.get(category="in_progress")
        open_issue = service.create_issue(self.agent, self.project, title="Patch panel")
        finished = service.create_issue(self.agent, self.project, title="Rewire IDF")
        planned = Sprint.objects.create(project=self.project, name="Sprint 2")

        service.set_sprint(self.agent, open_issue, self.sprint)
        service.set_sprint(self.agent, finished, self.sprint)
        service.move_issue(self.agent, finished, done)
        service.move_issue(self.agent, open_issue, in_progress)
        service.start_sprint(self.agent, self.sprint, "2026-11-02", "2026-11-13")

        service.complete_sprint(self.agent, self.sprint)
        open_issue.refresh_from_db()
        finished.refresh_from_db()
        self.sprint.refresh_from_db()
        self.assertEqual(self.sprint.state, "closed")
        self.assertIsNotNone(self.sprint.closed_at)
        self.assertIsNone(open_issue.sprint)
        self.assertEqual(finished.sprint, self.sprint)

        reopened = Sprint.objects.create(project=self.project, name="Sprint 1b")
        service.set_sprint(self.agent, open_issue, reopened)
        service.complete_sprint(self.agent, reopened, move_open_to=planned)
        open_issue.refresh_from_db()
        self.assertEqual(open_issue.sprint, planned)
        self.assertTrue(open_issue.events.filter(kind="sprint_added").exists())

    def test_complete_sprint_refuses_a_closed_or_foreign_target(self):
        other = service.create_project(self.admin, "SVC", "Services", "kanban")
        foreign = Sprint.objects.create(project=other, name="Elsewhere")
        closed = Sprint.objects.create(
            project=self.project, name="Sprint 0", state="closed", closed_at=timezone.now()
        )
        with self.assertRaises(ValidationError):
            service.complete_sprint(self.agent, self.sprint, move_open_to=foreign)
        with self.assertRaises(ValidationError):
            service.complete_sprint(self.agent, self.sprint, move_open_to=closed)


class EventTests(TestCase):
    def setUp(self):
        self.admin = make_user("coral", "admin")
        self.agent = make_user("aria", "agent")
        CostSettings.objects.create(pk=1, default_hours_per_point="4.00")
        self.project = service.create_project(self.admin, "NET", "Networking", "scrum")
        self.sprint = Sprint.objects.create(project=self.project, name="Sprint 1")

    def test_events_are_recorded(self):
        issue = service.create_issue(self.agent, self.project, title="Patch panel")
        created = issue.events.get(kind="created")
        self.assertEqual(created.actor, self.agent)

        later = service.create_issue(self.agent, self.project, title="Second")
        issue.refresh_from_db()
        self.assertEqual(issue.number, 1)
        self.assertEqual(later.number, 2)

        done = self.project.columns.get(category="done")
        in_progress = self.project.columns.get(category="in_progress")
        service.move_issue(self.agent, issue, in_progress)
        moved = issue.events.filter(kind="moved").first()
        self.assertEqual(
            {k: moved.data[k] for k in ("from_category", "to_category")},
            {"from_category": "todo", "to_category": "in_progress"},
        )

        service.move_issue(self.agent, issue, done)
        moved_again = list(issue.events.filter(kind="moved"))[-1]
        self.assertEqual(moved_again.data["to"], done.id)
        self.assertEqual(moved_again.data["to_category"], "done")

        service.set_points(self.agent, issue, 3)
        points = issue.events.get(kind="points")
        self.assertEqual(points.data, {"from": None, "to": 3})

        service.set_sprint(self.agent, issue, self.sprint)
        self.assertEqual(issue.events.get(kind="sprint_added").data["sprint"], self.sprint.id)
        service.set_sprint(self.agent, issue, None)
        self.assertEqual(issue.events.get(kind="sprint_removed").data["sprint"], self.sprint.id)

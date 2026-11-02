"""The four Projects-rail widgets and the ``project`` setting's options feed."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.dashboards.contract import WIDGET_SCHEMA_VERSION, validate_payload
from apps.dashboards.data import widget_data
from apps.dashboards.widgets import GROUPS, WIDGET_REGISTRY
from apps.projects import service
from apps.projects.models import CostSettings, PersonRate, Sprint
from apps.projects.test_backlog import make_user

KINDS = ("sprint_burndown", "team_load", "my_issues", "project_cost")


class ProjectWidgetTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.admin = make_user("coral", "admin")
        self.customer = make_user("boa", "customer")
        CostSettings.objects.create(pk=1, default_hours_per_point="4.00")
        self.project = service.create_project(self.admin, "NET", "Field Networking", "scrum")
        self.todo = self.project.columns.get(category="todo")
        self.doing = self.project.columns.get(category="in_progress")
        self.done = self.project.columns.get(category="done")

    def issue(self, title="Replace the edge switch", assignee=None, **fields):
        return service.create_issue(
            self.admin, self.project, title=title, assignee=assignee, **fields
        )

    def sprint(self, name="Kickoff sprint", **fields):
        return Sprint.objects.create(project=self.project, name=name, **fields)


class RegistryTests(ProjectWidgetTests):
    def test_registry_groups_include_projects(self):
        self.assertIn("projects", GROUPS)
        for kind in KINDS:
            self.assertEqual(WIDGET_REGISTRY[kind]["group"], "projects", kind)

    def test_new_widgets_return_valid_envelopes(self):
        for kind in KINDS:
            for settings in ({}, {"project": "net"}):
                payload = widget_data(kind, settings, self.agent)
                self.assertEqual(payload["version"], WIDGET_SCHEMA_VERSION, kind)
                self.assertEqual(payload["shape"], WIDGET_REGISTRY[kind]["shape"], kind)
                validate_payload(payload["shape"], payload["data"])


class BurndownWidgetTests(ProjectWidgetTests):
    def test_sprint_burndown_without_an_active_sprint_is_empty(self):
        self.sprint(state="planned", start_date=None, end_date=None)
        data = widget_data("sprint_burndown", {"project": "net"}, self.agent)["data"]
        self.assertEqual(
            data,
            {
                "kind": "line",
                "labels": [],
                "series": [{"name": "Remaining", "values": []}],
            },
        )

    def test_sprint_burndown_of_an_active_sprint_has_a_remaining_series(self):
        sprint = self.sprint()
        service.set_sprint(self.admin, self.issue(story_points=5), sprint)
        today = timezone.localdate()
        service.start_sprint(self.admin, sprint, today - timedelta(days=1), today)
        data = widget_data("sprint_burndown", {"project": "NET"}, self.agent)["data"]
        self.assertEqual(data["kind"], "line")
        self.assertEqual([s["name"] for s in data["series"]], ["Remaining", "Ideal"])
        self.assertEqual(data["series"][0]["values"][-1], 5)


class TeamLoadWidgetTests(ProjectWidgetTests):
    def test_team_load_without_a_project_asks_for_one(self):
        data = widget_data("team_load", {}, self.agent)["data"]
        self.assertEqual(data["columns"], ["Person", "Committed", "Usual"])
        self.assertTrue(data["rows"][0][0].startswith("Pick a project"))

    def test_team_load_lists_committed_points(self):
        sprint = self.sprint(state="active")
        service.set_sprint(
            self.admin, self.issue(title="Commit five", assignee=self.agent, story_points=5), sprint
        )
        rows = widget_data("team_load", {"project": "net"}, self.agent)["data"]["rows"]
        self.assertIn(["aria", 5, "—"], rows)


class MyIssuesWidgetTests(ProjectWidgetTests):
    def test_my_issues_lists_only_the_viewers_open_issues(self):
        mine = self.issue(title="Mine is open", assignee=self.agent)
        finished = self.issue(title="Mine is finished", assignee=self.agent)
        service.move_issue(self.admin, finished, self.done)
        someone_else = make_user("denise", "agent")
        theirs = self.issue(title="Not mine", assignee=someone_else)
        subtask = self.issue(title="Sub of mine", assignee=self.agent, type="subtask", parent=mine)

        items = widget_data("my_issues", {}, self.agent)["data"]["items"]
        titles = [item["title"] for item in items]

        self.assertIn(f"{mine.key} Mine is open", titles)
        joined = " ".join(titles)
        self.assertNotIn(finished.title, joined)
        self.assertNotIn(theirs.title, joined)
        self.assertNotIn(subtask.title, joined)

    def test_my_issues_of_an_archived_project_is_empty(self):
        self.issue(title="Filed away", assignee=self.agent)
        self.project.is_archived = True
        self.project.save(update_fields=["is_archived"])
        data = widget_data("my_issues", {}, self.agent)["data"]
        self.assertEqual(data["items"], [])
        self.assertEqual(data["empty"], "No open project issues are assigned to you.")


class ProjectCostWidgetTests(ProjectWidgetTests):
    def test_project_cost_widget_hides_cost_from_agents_without_the_setting(self):
        hidden = widget_data("project_cost", {"project": "NET"}, self.agent)["data"]
        self.assertEqual(hidden["label"], "Cost hidden")
        self.assertEqual(hidden["value"], 0)

        CostSettings.get_solo()
        CostSettings.objects.filter(pk=1).update(show_cost_totals_to_agents=True)
        shown = widget_data("project_cost", {"project": "net"}, self.agent)["data"]
        self.assertTrue(shown["label"].startswith("Spent on NET"), shown["label"])

    def test_project_cost_counts_finished_work_and_notes_whats_left_out(self):
        CostSettings.objects.filter(pk=1).update(show_cost_totals_to_agents=True)
        PersonRate.objects.create(user=self.agent, hourly_wage=Decimal("20.00"))
        priced = self.issue(title="Priced work", assignee=self.agent, story_points=3)
        unpriced = self.issue(title="No points")
        service.move_issue(self.admin, priced, self.done)
        service.move_issue(self.admin, unpriced, self.done)

        data = widget_data("project_cost", {"project": "NET"}, self.agent)["data"]
        # 3 points × the 4.00 default hours per point × $20 an hour, whole units.
        self.assertEqual(data["value"], 240)
        self.assertEqual(data["label"], "Spent on NET (USD)")
        self.assertEqual(data["tone"], "info")
        self.assertEqual(data["sub"], "1 issue left out")

    def test_project_cost_without_a_project_asks_for_one(self):
        data = widget_data("project_cost", {}, self.agent)["data"]
        self.assertEqual(data["value"], 0)
        self.assertTrue(data["label"].startswith("Pick a project"))


class ProjectOptionsTests(ProjectWidgetTests):
    def test_project_options_endpoint(self):
        service.create_project(self.admin, "OLD", "Retired Wiring", "scrum")
        self.project.is_archived = True
        self.project.save(update_fields=["is_archived"])

        client = APIClient()
        client.force_authenticate(self.agent)
        body = client.get(reverse("dashboards:dashboard-options-project")).json()
        self.assertIn(["", "Pick a project"], body)
        self.assertIn(["OLD", "OLD — Retired Wiring"], body)
        self.assertNotIn(["NET", "NET — Field Networking"], body)

        self.project.is_archived = False
        self.project.save(update_fields=["is_archived"])
        body = client.get(reverse("dashboards:dashboard-options-project")).json()
        self.assertIn(["NET", "NET — Field Networking"], body)

        client.force_authenticate(self.customer)
        response = client.get(reverse("dashboards:dashboard-options-project"))
        self.assertEqual(response.status_code, 403)

"""The backlog screen: its JSON, sprint actions, load per person and script."""

import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.projects import cost, service
from apps.projects.models import CostSettings, Issue, PersonRate, Project, Sprint

#: Titles and names no migration or fixture uses, so counts stay ours to compare.
TITLE = "Replace the edge switch"
PROJECT_NAME = "Field Networking"


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class BacklogTest(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.admin = make_user("coral", "admin")
        self.customer = make_user("boa", "customer")
        CostSettings.objects.create(pk=1, default_hours_per_point="4.00")
        self.project = service.create_project(self.admin, "NET", PROJECT_NAME, "scrum")
        self.todo = self.project.columns.get(category="todo")
        self.doing = self.project.columns.get(category="in_progress")
        self.done = self.project.columns.get(category="done")

    def issue(self, title=TITLE, **fields):
        return service.create_issue(self.admin, self.project, title=title, **fields)

    def sprint(self, name="Kickoff sprint", **fields):
        return Sprint.objects.create(project=self.project, name=name, **fields)

    def login(self, user):
        self.assertTrue(self.client.login(username=user.username, password="pw"))

    def post(self, name, payload=None, *args):
        return self.client.post(
            reverse(f"projects:{name}", args=["NET", *args]),
            data=json.dumps(payload or {}),
            content_type="application/json",
        )

    def rank_url(self, key="NET"):
        return reverse("projects:backlog_rank", args=[key])

    def rank(self, issue, before=None, sprint=None):
        return self.client.post(
            self.rank_url(),
            data=json.dumps(
                {
                    "issue": issue.id,
                    "before": None if before is None else before.id,
                    "sprint": None if sprint is None else sprint.id,
                }
            ),
            content_type="application/json",
        )

    def data(self, key="NET"):
        response = self.client.get(reverse("projects:backlog_data", args=[key]))
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def order(self, sprint=None):
        """The list's issue numbers, in the order the screen draws them."""
        issues = Issue.objects.filter(project=self.project)
        issues = issues.filter(sprint=sprint) if sprint else issues.filter(sprint__isnull=True)
        return list(issues.order_by("rank", "number").values_list("number", flat=True))


class BacklogDataTests(BacklogTest):
    def test_backlog_data_shape_and_customer_403(self):
        planned = self.sprint()
        active = self.sprint("Doing sprint", state="active")
        first = self.issue(title="First in the backlog", story_points=3)
        self.issue(title="In the active sprint", sprint=None, assignee=self.agent, story_points=5)
        service.set_sprint(self.agent, first, active)
        second = self.issue(title="Second in the backlog")
        service.set_sprint(self.agent, second, planned)

        self.login(self.agent)
        body = self.data()
        self.assertEqual(
            [sprint["name"] for sprint in body["sprints"]],
            ["Doing sprint", "Kickoff sprint"],
        )
        active_row = body["sprints"][0]
        self.assertEqual(
            set(active_row),
            {"id", "name", "goal", "state", "start_date", "end_date", "issues", "points"},
        )
        self.assertEqual([row["key"] for row in active_row["issues"]], ["NET-1"])
        self.assertEqual(active_row["points"], 3)
        self.assertEqual(
            set(active_row["issues"][0]),
            {
                "id",
                "key",
                "title",
                "type",
                "points",
                "assignee",
                "assignee_name",
                "column",
                "rank",
                "url",
            },
        )
        self.assertEqual([row["key"] for row in body["backlog"]], ["NET-2"])

        self.login(self.customer)
        response = self.client.get(reverse("projects:backlog_data", args=["NET"]))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_sent_to_sign_in(self):
        response = self.client.get(reverse("projects:backlog_data", args=["NET"]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)


class RankTests(BacklogTest):
    def test_rank_moves_into_a_sprint_above_a_neighbour(self):
        planned = self.sprint()
        top = self.issue(title="Top of the sprint")
        bottom = self.issue(title="Bottom of the sprint")
        service.set_sprint(self.agent, top, planned)
        service.set_sprint(self.agent, bottom, planned)
        dragged = self.issue(title="From the backlog")

        self.login(self.agent)
        response = self.rank(dragged, before=top, sprint=planned)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.order(planned), [dragged.number, top.number, bottom.number])
        self.assertEqual(self.order(), [])
        dragged.refresh_from_db()
        self.assertEqual(dragged.sprint, planned)
        self.assertTrue(dragged.events.filter(kind="sprint_added").exists())

    def test_rank_to_the_end_of_the_backlog(self):
        first = self.issue(title="Already in the backlog")
        dragged = self.issue(title="Coming back from a sprint")
        planned = self.sprint()
        service.set_sprint(self.agent, dragged, planned)

        self.login(self.agent)
        response = self.rank(dragged, before=None, sprint=None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.order(), [first.number, dragged.number])

    def test_rank_renumbers_when_neighbours_are_too_close(self):
        planned = self.sprint()
        first = self.issue(title="First in the sprint")
        second = self.issue(title="Second in the sprint")
        dragged = self.issue(title="Squeezed between")
        for issue in (first, second, dragged):
            service.set_sprint(self.agent, issue, planned)
        Issue.objects.filter(pk=first.pk).update(rank=1.0)
        Issue.objects.filter(pk=second.pk).update(rank=1.0 + 1e-9)

        self.login(self.agent)
        response = self.rank(dragged, before=second, sprint=planned)
        self.assertEqual(response.status_code, 200)
        dragged.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(
            [Issue.objects.get(pk=pk).rank for pk in (dragged.pk, second.pk)],
            [2.0, 3.0],
        )
        self.assertEqual(self.order(planned), [first.number, dragged.number, second.number])

    def test_subtask_cannot_be_ranked(self):
        parent = self.issue(title="Parent story")
        child = service.create_issue(
            self.agent, self.project, title="Crimp the lead", type="subtask", parent=parent
        )
        planned = self.sprint()

        self.login(self.agent)
        response = self.rank(child, before=None, sprint=planned)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Sub-task", response.json()["error"])
        child.refresh_from_db()
        self.assertIsNone(child.sprint)

    def test_closed_sprint_cannot_be_edited_or_receive_issues(self):
        closed = self.sprint("Finished sprint", state="closed")
        dragged = self.issue(title="Nobody goes here")

        self.login(self.agent)
        response = self.rank(dragged, before=None, sprint=closed)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Cannot add issues to a closed sprint.",
        )
        dragged.refresh_from_db()
        self.assertIsNone(dragged.sprint)

        edit = self.post("sprint_edit", {"name": "Rewritten history"}, closed.id)
        self.assertEqual(edit.status_code, 400)
        self.assertEqual(edit.json()["error"], "A closed sprint cannot be edited.")
        closed.refresh_from_db()
        self.assertEqual(closed.name, "Finished sprint")

    def test_rank_within_a_list_uses_the_neighbour_it_names(self):
        planned = self.sprint()
        top = self.issue(title="Top of the sprint")
        bottom = self.issue(title="Bottom of the sprint")
        service.set_sprint(self.agent, top, planned)
        service.set_sprint(self.agent, bottom, planned)
        squeezed = self.issue(title="Reordered inside the sprint")
        service.set_sprint(self.agent, squeezed, planned)

        self.login(self.agent)
        response = self.rank(squeezed, before=top, sprint=planned)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.order(planned),
            [squeezed.number, top.number, bottom.number],
        )

    def test_customer_cannot_rank_anything(self):
        issue = self.issue()
        self.login(self.customer)
        response = self.client.post(
            self.rank_url(),
            data=json.dumps({"issue": issue.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class SprintActionTests(BacklogTest):
    def test_sprint_create_default_name(self):
        self.sprint(name="NET Sprint 2")
        self.login(self.agent)
        response = self.post("sprint_create", {"goal": "Wire the annexe"})
        self.assertEqual(response.status_code, 201)
        created = Sprint.objects.get(pk=response.json()["id"])
        self.assertEqual(created.name, "NET Sprint 3")
        self.assertEqual(created.goal, "Wire the annexe")
        self.assertEqual(created.state, "planned")
        self.assertIsNone(created.start_date)

        named = self.post("sprint_create", {"name": "  Annexe cabling  "})
        self.assertEqual(Sprint.objects.get(pk=named.json()["id"]).name, "Annexe cabling")

    def test_start_needs_valid_dates_and_only_one_active(self):
        first = self.sprint("First sprint")
        second = self.sprint("Second sprint")
        self.login(self.agent)

        bad = self.post(
            "sprint_start",
            {"start_date": "2026-11-13", "end_date": "2026-11-02"},
            first.id,
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(
            bad.json()["error"],
            "The end date cannot be before the start date.",
        )
        first.refresh_from_db()
        self.assertEqual(first.state, "planned")

        malformed = self.post("sprint_start", {"start_date": "13/11/2026"}, first.id)
        self.assertEqual(malformed.status_code, 400)
        self.assertIn("start date", malformed.json()["error"])

        started = self.post(
            "sprint_start",
            {"start_date": "2026-11-02", "end_date": "2026-11-13"},
            first.id,
        )
        self.assertEqual(started.status_code, 200)
        first.refresh_from_db()
        self.assertEqual(first.state, "active")
        self.assertEqual(first.start_date.isoformat(), "2026-11-02")
        self.assertEqual(first.end_date.isoformat(), "2026-11-13")

        clash = self.post(
            "sprint_start",
            {"start_date": "2026-11-16", "end_date": "2026-11-27"},
            second.id,
        )
        self.assertEqual(clash.status_code, 400)

    def test_complete_moves_open_issues_and_reports_how_many(self):
        active = self.sprint("Winding down", state="active")
        planned = self.sprint("Next up")
        finishing = self.issue(title="Done this sprint")
        lingering = self.issue(title="Carries over")
        also_lingering = self.issue(title="Carries over too")
        for issue in (finishing, lingering, also_lingering):
            service.set_sprint(self.agent, issue, active)
        service.move_issue(self.agent, finishing, self.done)

        self.login(self.agent)
        response = self.client.post(
            reverse("projects:sprint_complete", args=["NET", active.id]),
            data=json.dumps({"move_open_to": planned.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"moved": 2})
        active.refresh_from_db()
        self.assertEqual(active.state, "closed")
        lingering.refresh_from_db()
        self.assertEqual(lingering.sprint, planned)
        finishing.refresh_from_db()
        self.assertEqual(finishing.sprint, active)

        to_backlog = self.sprint("Another", state="active")
        stray = self.issue(title="Stray work")
        service.set_sprint(self.agent, stray, to_backlog)
        dropped = self.client.post(
            reverse("projects:sprint_complete", args=["NET", to_backlog.id]),
            data=json.dumps({"move_open_to": None}),
            content_type="application/json",
        )
        self.assertEqual(dropped.json(), {"moved": 1})

    def test_edit_renames_a_sprint_and_moves_its_dates(self):
        planned = self.sprint()
        self.login(self.agent)
        response = self.post(
            "sprint_edit",
            {
                "name": "Annexe cabling",
                "goal": "Everything wired",
                "start_date": "2026-12-01",
                "end_date": "2026-12-14",
            },
            planned.id,
        )
        self.assertEqual(response.status_code, 200)
        planned.refresh_from_db()
        self.assertEqual(planned.name, "Annexe cabling")
        self.assertEqual(planned.goal, "Everything wired")
        self.assertEqual(planned.start_date.isoformat(), "2026-12-01")
        self.assertEqual(planned.end_date.isoformat(), "2026-12-14")

    def test_sprint_actions_reach_the_right_sprint(self):
        mine = self.sprint("Ours")
        other = service.create_project(self.admin, "SVC", "Services", "scrum")
        theirs = Sprint.objects.create(project=other, name="Theirs")

        self.login(self.agent)
        response = self.client.post(
            reverse("projects:sprint_edit", args=["NET", theirs.id]),
            data=json.dumps({"name": "Hijacked"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.name, "Theirs")

        renamed = self.client.post(
            reverse("projects:sprint_edit", args=["NET", mine.id]),
            data=json.dumps({"name": "Renamed"}),
            content_type="application/json",
        )
        self.assertEqual(renamed.status_code, 200)
        mine.refresh_from_db()
        self.assertEqual(mine.name, "Renamed")


class LoadTests(BacklogTest):
    def setUp(self):
        super().setUp()
        self.lead = make_user("monk", "agent")
        Project.objects.filter(pk=self.project.pk).update(lead=self.lead)
        self.project.refresh_from_db()

    def velocity_of(self, user, points_per_sprint=4):
        """Three closed sprints of completed work, so velocity is known.

        A closed sprint refuses new work through the service, so the history is
        written directly — it happened before this test ever looked at it.
        """
        PersonRate.objects.create(user=user, hourly_wage=Decimal("30.00"), sprint_hours="40.0")
        clock = self.project.created_at
        for index in range(3):
            started = clock + timezone.timedelta(days=index * 30)
            sprint = Sprint.objects.create(
                project=self.project,
                name=f"History {index}",
                state="closed",
                started_at=started,
                closed_at=started + timezone.timedelta(days=1),
            )
            finished = service.create_issue(
                self.admin,
                self.project,
                title=f"Finished {index} by {user.username}",
                assignee=user,
                story_points=points_per_sprint,
            )
            finished.sprint = sprint
            finished.column = self.done
            finished.completed_by = user
            finished.completed_at = started + timezone.timedelta(hours=12)
            finished.save()
        return cost.velocity(user)

    def test_load_counts_points_per_person_excluding_subtasks(self):
        planned = self.sprint()
        self.velocity_of(self.agent, points_per_sprint=4)
        story = self.issue(title="Story for aria", assignee=self.agent, story_points=8)
        child = service.create_issue(
            self.agent,
            self.project,
            title="Crimp the lead",
            type="subtask",
            parent=story,
        )
        service.set_sprint(self.agent, story, planned)
        child.refresh_from_db()
        self.assertEqual(child.sprint, planned)

        self.login(self.agent)
        body = self.data()
        by_name = {person["name"]: person for person in body["people"]}
        self.assertEqual(
            sorted(by_name),
            sorted([self.agent.get_full_name() or self.agent.username, self.lead.username]),
        )
        self.assertEqual(by_name["aria"]["committed"], 8)
        self.assertEqual(by_name["aria"]["velocity"], 4.0)
        self.assertEqual(by_name["monk"]["committed"], 0)
        self.assertIsNone(by_name["monk"]["velocity"])
        text = json.dumps(body).lower()
        for forbidden in ["hourly_wage", "cost", "wage", "30.00", "currency"]:
            self.assertNotIn(forbidden, text)


from django.utils import timezone  # noqa: E402  (used by LoadTests)


class BacklogPageTests(BacklogTest):
    def test_backlog_lives_under_the_board_for_scrum(self):
        self.login(self.agent)
        old = self.client.get(reverse("projects:backlog", args=["NET"]))
        self.assertRedirects(
            old, reverse("projects:board", args=["NET"]) + "#backlog", fetch_redirect_response=False
        )
        page = self.client.get(reverse("projects:board", args=["NET"])).content.decode()
        self.assertIn('id="bl-lists"', page)
        self.assertIn(reverse("projects:backlog_data", args=["NET"]), page)
        self.assertIn("jackil-backlog.js", page)

    def test_standalone_backlog_still_renders(self):
        self.login(self.agent)
        response = self.client.get(reverse("projects:backlog", args=["NET"]), {"standalone": "1"})
        self.assertContains(response, 'id="bl-lists"')

    def test_kanban_board_has_no_backlog(self):
        boards = service.create_project(self.admin, "BRD", "Board Room", "kanban")
        self.login(self.agent)
        kanban = self.client.get(reverse("projects:board", args=[boards.key])).content.decode()
        self.assertNotIn('id="bl-lists"', kanban)
        self.assertNotIn("jackil-backlog.js", kanban)

    def test_project_screens_share_the_three_tabs(self):
        self.login(self.admin)
        for name in ("board", "project_detail", "reports", "project_settings"):
            page = self.client.get(reverse(f"projects:{name}", args=["NET"])).content.decode()
            self.assertIn('class="tab t-sky"', page, name)
            self.assertIn('class="tab t-lav"', page, name)
            self.assertIn('class="tab t-peach"', page, name)

    def test_agents_do_not_get_the_settings_tab(self):
        self.login(self.agent)
        page = self.client.get(reverse("projects:board", args=["NET"])).content.decode()
        self.assertIn('class="tab t-sky"', page)
        self.assertNotIn('class="tab t-peach"', page)

    def test_customer_cannot_open_the_page(self):
        self.login(self.customer)
        response = self.client.get(reverse("projects:backlog", args=["NET"]))
        self.assertEqual(response.status_code, 403)


class BacklogScriptTests(SimpleTestCase):
    def setUp(self):
        self.script = Path(settings.BASE_DIR, "static/js/jackil-backlog.js").read_text()

    def test_script_wires_the_drag_and_the_dialogs(self):
        for literal in [
            "'dragstart'",
            "'drop'",
            "'dragover'",
            "data-issue-id",
            "closest('.bl-row')",
            "data-bl-move",
            "bl-move-modal",
            "showToast",
            "escHtml",
        ]:
            self.assertIn(literal, self.script)

    def test_script_never_assigns_the_whole_payload_as_markup(self):
        self.assertNotIn("innerHTML = data", self.script)
        self.assertNotIn("border-left", self.script)

    def test_backlog_css_has_no_side_stripes(self):
        css = Path(settings.BASE_DIR, "static/css/style.css").read_text()
        block = css.split("/* Backlog (M5 p03b) */", 1)[1]
        self.assertNotIn("border-left", block)
        self.assertNotIn("border-right", block)

"""Projects pages: permissions, URLs, filters, events, cost visibility, link types."""

import re
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.links.registry import get_resolver
from apps.projects import service
from apps.projects.links import IssueResolver, ProjectResolver
from apps.projects.models import (
    CostSettings,
    Issue,
    IssueEvent,
    PersonRate,
    Project,
    Sprint,
)
from apps.wiki.markdown import render as render_markdown

#: Titles no migration or fixture uses, so counts stay ours to compare.
TITLE = "Replace the edge switch"
PROJECT_NAME = "Field Networking"


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class ViewTest(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.admin = make_user("coral", "admin")
        self.customer = make_user("boa", "customer")
        self.project = service.create_project(self.admin, "NET", PROJECT_NAME, "scrum")
        self.todo = self.project.columns.get(category="todo")
        self.doing = self.project.columns.get(category="in_progress")
        self.done = self.project.columns.get(category="done")

    def issue(self, title=TITLE, **fields):
        return service.create_issue(self.admin, self.project, title=title, **fields)

    def login(self, user):
        self.assertTrue(self.client.login(username=user.username, password="pw"))


class CustomerBlockedTests(ViewTest):
    URLS = [
        ("projects:project_list", []),
        ("projects:project_create", []),
        ("projects:project_detail", ["NET"]),
        ("projects:project_settings", ["NET"]),
        ("projects:issue_create", ["NET"]),
        ("projects:issue_detail", [("NET", 1)]),
        ("projects:issue_edit", [("NET", 1)]),
        ("projects:issue_move", [("NET", 1)]),
        ("projects:issue_comment", [("NET", 1)]),
    ]

    def test_customer_gets_403_everywhere(self):
        self.issue()
        self.login(self.customer)
        for name, args in self.URLS:
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("projects:project_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


class PermissionTests(ViewTest):
    def test_agent_cannot_create_a_project_or_open_settings(self):
        self.login(self.agent)
        self.assertEqual(self.client.get(reverse("projects:project_create")).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("projects:project_create"),
                {"key": "FLD", "name": "Fieldwork", "method": "scrum", "description": ""},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("projects:project_settings", args=["NET"])).status_code, 403
        )
        self.assertFalse(Project.objects.filter(key="FLD").exists())

    def test_agent_sees_the_list_and_the_project(self):
        self.login(self.agent)
        self.assertEqual(self.client.get(reverse("projects:project_list")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("projects:project_detail", args=["NET"])).status_code, 200
        )


class ProjectCrudTests(ViewTest):
    def test_admin_creates_a_project_with_default_columns(self):
        self.login(self.admin)
        response = self.client.post(
            reverse("projects:project_create"),
            {
                "key": "FLD",
                "name": "Fieldwork",
                "method": "kanban",
                "lead": self.agent.pk,
                "description": "On-site work",
            },
        )
        self.assertRedirects(response, reverse("projects:project_detail", args=["FLD"]))
        project = Project.objects.get(key="FLD")
        self.assertEqual(
            [(c.name, c.category, c.order) for c in project.columns.all()],
            [("To do", "todo", 0), ("In progress", "in_progress", 1), ("Done", "done", 2)],
        )
        self.assertEqual(project.lead_id, self.agent.pk)

    def test_lowercase_key_is_uppercased(self):
        self.login(self.admin)
        self.client.post(
            reverse("projects:project_create"),
            {"key": "fld", "name": "Fieldwork", "method": "scrum", "description": ""},
        )
        self.assertTrue(Project.objects.filter(key="FLD", name="Fieldwork").exists())

    def test_project_list_hides_archived_by_default(self):
        service.create_project(self.admin, "OLD", "Old Network", "scrum")
        self.assertEqual(
            Project.objects.count(), 2, "the two projects are both active to begin with"
        )
        self.login(self.admin)
        listed = self.client.get(reverse("projects:project_list")).content.decode()
        self.assertIn(PROJECT_NAME, listed)
        self.assertIn("Old Network", listed)

        Project.objects.filter(key="OLD").update(is_archived=True)
        listed = self.client.get(reverse("projects:project_list")).content.decode()
        self.assertNotIn("Old Network", listed)
        self.assertIn(PROJECT_NAME, listed)

        shown = self.client.get(
            reverse("projects:project_list"), {"archived": "1"}
        ).content.decode()
        self.assertIn("Old Network", shown)
        self.assertNotIn(PROJECT_NAME, shown)

    def test_settings_edits_fields_and_columns(self):
        self.login(self.admin)
        response = self.client.post(
            reverse("projects:project_settings", args=["NET"]),
            {
                "key": "NET",
                "name": "Field Networking Two",
                "method": "kanban",
                "description": "",
            },
        )
        self.assertRedirects(response, reverse("projects:project_detail", args=["NET"]))
        project = Project.objects.get(pk=self.project.pk)
        self.assertEqual(project.name, "Field Networking Two")
        self.assertEqual(project.method, "kanban")

        response = self.client.post(
            reverse("projects:project_settings", args=["NET"]),
            {
                "action": "columns",
                f"name-{self.doing.pk}": "Doing",
                f"category-{self.doing.pk}": "in_progress",
                f"order-{self.doing.pk}": "1",
                f"name-{self.todo.pk}": self.todo.name,
                f"category-{self.todo.pk}": "todo",
                f"order-{self.todo.pk}": "0",
                f"name-{self.done.pk}": self.done.name,
                f"category-{self.done.pk}": "done",
                f"order-{self.done.pk}": "2",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(self.project.columns.order_by("order").values_list("name", flat=True)),
            ["To do", "Doing", "Done"],
        )

    def test_column_added_and_only_deleted_when_empty(self):
        self.login(self.admin)
        self.client.post(
            reverse("projects:project_settings", args=["NET"]),
            {"action": "columns", "add_column": "1", "name": "Blocked", "category": "todo"},
        )
        blocked = self.project.columns.filter(name="Blocked").first()
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked.order, 3)

        issue = self.issue()
        service.move_issue(self.admin, issue, blocked)
        self.client.post(
            reverse("projects:project_settings", args=["NET"]),
            {"action": "columns", "delete_column": blocked.pk},
        )
        self.assertTrue(self.project.columns.filter(pk=blocked.pk).exists())

        service.move_issue(self.admin, issue, self.todo)
        self.client.post(
            reverse("projects:project_settings", args=["NET"]),
            {"action": "columns", "delete_column": blocked.pk},
        )
        self.assertFalse(self.project.columns.filter(pk=blocked.pk).exists())


class IssueUrlTests(ViewTest):
    def test_issue_url_is_not_taken_by_the_project_route(self):
        issue = self.issue()
        detail = reverse("projects:issue_detail", args=[("NET", issue.number)])
        self.assertEqual(detail, f"/projects/NET-{issue.number}/")
        self.login(self.agent)
        response = self.client.get(detail)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, issue.title)

        listed = self.client.get(reverse("projects:project_detail", args=["NET"]))
        self.assertContains(listed, PROJECT_NAME)

    def test_issue_create_numbers_and_redirects_to_KEY_n(self):
        self.login(self.agent)
        response = self.client.post(
            reverse("projects:issue_create", args=["NET"]),
            {
                "type": "story",
                "title": TITLE,
                "description": "Done at the rack",
                "priority": "high",
            },
        )
        issue = Issue.objects.get(title=TITLE)
        self.assertEqual(issue.number, 1)
        self.assertRedirects(response, reverse("projects:issue_detail", args=[("NET", 1)]))
        self.assertEqual(issue.column_id, self.todo.pk)
        self.assertEqual(issue.reporter_id, self.agent.pk)

        self.client.post(
            reverse("projects:issue_create", args=["NET"]),
            {
                "type": "task",
                "title": "Label the patch panel",
                "description": "",
                "priority": "low",
            },
        )
        self.assertEqual(Issue.objects.get(title="Label the patch panel").number, 2)


class IssueFilterTests(ViewTest):
    def setUp(self):
        super().setUp()
        self.story = self.issue(title=TITLE, type="story", assignee=self.agent)
        self.bug = self.issue(title="Patch panel is loose", type="bug")
        service.move_issue(self.admin, self.bug, self.done)

    def filtered_titles(self, **params):
        response = self.client.get(reverse("projects:project_detail", args=["NET"]), params)
        return [
            title
            for title, issue in ((TITLE, self.story), ("Patch panel is loose", self.bug))
            if f'href="/projects/{issue.key}/"' in response.content.decode()
        ]

    def test_issue_filters_type_assignee_status_q(self):
        self.login(self.agent)
        self.assertEqual(
            self.filtered_titles(), [TITLE, "Patch panel is loose"], "no filter shows both"
        )
        self.assertEqual(self.filtered_titles(type="bug"), ["Patch panel is loose"])
        self.assertEqual(self.filtered_titles(assignee="me"), [TITLE])
        self.assertEqual(self.filtered_titles(assignee="none"), ["Patch panel is loose"])
        self.assertEqual(self.filtered_titles(assignee=str(self.agent.pk)), [TITLE])
        self.assertEqual(self.filtered_titles(status="done"), ["Patch panel is loose"])
        self.assertEqual(self.filtered_titles(status="todo"), [TITLE])
        self.assertEqual(self.filtered_titles(q="patch"), ["Patch panel is loose"])
        self.assertEqual(self.filtered_titles(q="switch"), [TITLE])
        self.assertEqual(self.filtered_titles(type="bug", status="todo"), [])


class SubtaskFormTests(ViewTest):
    def setUp(self):
        super().setUp()
        self.story = self.issue(title=TITLE, type="story", story_points=5)

    def test_subtask_form_hides_points_and_requires_a_parent(self):
        self.login(self.agent)
        page = self.client.get(
            reverse("projects:issue_create", args=["NET"]), {"type": "subtask", "parent": "NET-1"}
        ).content.decode()
        fields = re.search(r'<form method="post".*?</form>', page, re.S)
        self.assertIsNotNone(fields, "no issue form on the page")
        self.assertNotIn(
            "data-points-field",
            fields.group(0),
            "a sub-task form must not offer a points box",
        )
        self.assertIn('name="parent"', page)
        self.assertIn(f'<option value="{self.story.pk}" selected>', page)

        response = self.client.post(
            reverse("projects:issue_create", args=["NET"]),
            {"type": "subtask", "title": "Crimp the lead", "description": "", "priority": "medium"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Issue.objects.filter(title="Crimp the lead").exists())
        self.assertContains(response, "A sub-task must sit under a story, task or bug.")

    def test_subtask_is_created_under_its_parent_with_no_points(self):
        self.login(self.agent)
        self.client.post(
            reverse("projects:issue_create", args=["NET"]),
            {
                "type": "subtask",
                "title": "Crimp the lead",
                "description": "",
                "priority": "medium",
                "parent": self.story.pk,
                "story_points": 8,
            },
        )
        subtask = Issue.objects.get(title="Crimp the lead")
        self.assertEqual(subtask.parent_id, self.story.pk)
        self.assertIsNone(subtask.story_points)


class IssueEditTests(ViewTest):
    def setUp(self):
        super().setUp()
        self.sprint = Sprint.objects.create(project=self.project, name="Sprint 4", state="active")

    def test_editing_points_and_sprint_records_events(self):
        issue = self.issue(title=TITLE, type="story", story_points=3)
        self.login(self.agent)
        self.client.post(
            reverse("projects:issue_edit", args=[("NET", issue.number)]),
            {
                "type": "story",
                "title": TITLE,
                "description": "",
                "priority": "medium",
                "story_points": 5,
                "sprint": self.sprint.pk,
            },
        )
        issue.refresh_from_db()
        self.assertEqual(issue.story_points, 5, "the form left a stale copy of the issue behind")
        self.assertEqual(issue.sprint_id, self.sprint.pk)
        events = {event.kind: event.data for event in issue.events.all()}
        self.assertIn("points", events)
        self.assertEqual(events["points"], {"from": 3, "to": 5})
        self.assertIn("sprint_added", events)
        self.assertEqual(events["sprint_added"], {"sprint": self.sprint.pk})

        page = self.client.get(
            reverse("projects:issue_detail", args=[("NET", issue.number)])
        ).content.decode()
        self.assertIn("Points 3 → 5", page)
        self.assertIn("Added to Sprint 4", page)

    def test_untouched_points_write_no_event(self):
        issue = self.issue(title=TITLE, type="story", story_points=3)
        self.login(self.agent)
        self.client.post(
            reverse("projects:issue_edit", args=[("NET", issue.number)]),
            {
                "type": "story",
                "title": "Title, same points",
                "description": "",
                "priority": "medium",
                "story_points": 3,
            },
        )
        self.assertFalse(issue.events.filter(kind="points").exists())
        self.assertFalse(issue.events.filter(kind="sprint_added").exists())
        issue.refresh_from_db()
        self.assertEqual(issue.title, "Title, same points")


class MoveTests(ViewTest):
    def setUp(self):
        super().setUp()
        PersonRate.objects.create(
            user=self.agent, hourly_wage=Decimal("20.00"), sprint_hours=Decimal("40.0")
        )
        CostSettings.objects.create(pk=1, default_hours_per_point=Decimal("4.00"), currency="USD")

    def test_move_to_done_freezes_cost(self):
        issue = self.issue(title=TITLE, type="story", assignee=self.agent, story_points=2)
        self.login(self.agent)
        self.client.post(
            reverse("projects:issue_move", args=[("NET", issue.number)]),
            {"column": self.done.pk},
        )
        issue.refresh_from_db()
        self.assertEqual(issue.column_id, self.done.pk)
        self.assertEqual(issue.frozen_cost, Decimal("160.00"))
        self.assertEqual(issue.completed_by_id, self.agent.pk)
        self.assertTrue(issue.events.filter(kind="moved").exists())
        self.assertContains(
            self.client.get(reverse("projects:issue_detail", args=[("NET", issue.number)])),
            "Moved to Done",
        )


class CommentTests(ViewTest):
    def test_comment_is_rendered_markdown_and_sanitised(self):
        issue = self.issue(title=TITLE)
        self.login(self.agent)
        response = self.client.post(
            reverse("projects:issue_comment", args=[("NET", issue.number)]),
            {"body": "**Done** <script>alert(1)</script>"},
        )
        self.assertRedirects(response, reverse("projects:issue_detail", args=[("NET", 1)]))
        page = self.client.get(reverse("projects:issue_detail", args=[("NET", issue.number)]))
        body = page.content.decode()
        self.assertIn("<strong>Done</strong>", body)
        comment = body.split('class="comment"', 1)[1]
        self.assertNotIn("<script>", comment)
        self.assertNotIn("<script>alert", comment)


class EpicTests(ViewTest):
    def test_epic_shows_children_and_points_total(self):
        epic = self.issue(title="Roll out the new switches", type="epic")
        first = self.issue(title=TITLE, type="story", story_points=3)
        second = self.issue(title="Write the runbook", type="story", story_points=2)
        for child in (first, second):
            child.parent = epic
            child.save()
        service.move_issue(self.admin, second, self.done)

        self.login(self.agent)
        page = self.client.get(reverse("projects:issue_detail", args=[("NET", epic.number)]))
        self.assertContains(page, TITLE)
        self.assertContains(page, "Write the runbook")
        self.assertContains(page, "5 points")
        self.assertContains(page, "1 of 2 done")

    def test_subtasks_are_listed_under_their_parent(self):
        story = self.issue(title=TITLE, type="story")
        subtask = self.issue(title="Crimp the lead", type="subtask", parent=story)
        self.login(self.agent)
        page = self.client.get(reverse("projects:issue_detail", args=[("NET", story.number)]))
        self.assertContains(page, subtask.key)
        self.assertContains(page, "Add sub-task")


class CostVisibilityTests(ViewTest):
    def setUp(self):
        super().setUp()
        CostSettings.objects.create(pk=1, default_hours_per_point=Decimal("4.00"), currency="USD")
        PersonRate.objects.create(
            user=self.agent, hourly_wage=Decimal("20.00"), sprint_hours=Decimal("40.0")
        )
        self.issue = self.issue(title=TITLE, type="story", assignee=self.agent, story_points=2)

    def cost_lines(self, user):
        self.login(user)
        return self.client.get(
            reverse("projects:issue_detail", args=[("NET", self.issue.number)])
        ).content.decode()

    def test_cost_line_hidden_from_agents_unless_setting_on(self):
        page = self.cost_lines(self.agent)
        self.assertNotIn("Cost", page)

        CostSettings.objects.filter(pk=1).update(show_cost_totals_to_agents=True)
        self.assertIn("USD 160.00", self.cost_lines(self.agent))

    def test_cost_line_always_visible_to_admins(self):
        self.assertIn("USD 160.00", self.cost_lines(self.admin))

    def test_cost_shows_not_set_without_a_wage(self):
        PersonRate.objects.filter(user=self.agent).update(hourly_wage=None)
        self.assertIn("not set", self.cost_lines(self.admin))

    def test_no_page_shows_a_wage(self):
        PersonRate.objects.filter(user=self.agent).update(
            hourly_wage=Decimal("45.00"), sprint_hours=Decimal("37.5")
        )
        self.login(self.agent)
        for user in (self.agent, self.admin):
            self.login(user)
            for url in (
                reverse("projects:issue_detail", args=[("NET", self.issue.number)]),
                reverse("projects:project_detail", args=["NET"]),
            ):
                with self.subTest(user=user.username, url=url):
                    page = self.client.get(url).content.decode()
                    self.assertNotIn("45.00", page)
                    self.assertNotIn("hours per point", page.lower())


class SidebarTests(ViewTest):
    def test_sidebar_has_projects_for_staff_only(self):
        for user, expected in ((self.agent, True), (self.admin, True), (self.customer, False)):
            with self.subTest(role=user.role):
                self.login(user)
                response = self.client.get(
                    reverse("projects:project_list") if expected else reverse("help:home")
                )
                body = response.content.decode()
                if expected:
                    self.assertIn('data-tip="Projects"', body)
                    self.assertIn("/projects/", body)
                else:
                    self.assertNotIn('data-tip="Projects"', body)


class LinkTypeTests(ViewTest):
    def setUp(self):
        super().setUp()
        self.issue = self.issue(title=TITLE, type="story")

    def test_card_and_project_link_types(self):
        card = get_resolver("card")
        self.assertIsInstance(card, IssueResolver)
        self.assertIsInstance(get_resolver("project"), ProjectResolver)

        by_pk = card.resolve([str(self.issue.pk)], self.agent)
        target = by_pk[str(self.issue.pk)]
        self.assertEqual(target.label, f"NET-1 {TITLE}")
        self.assertEqual(target.url, "/projects/NET-1/")
        self.assertEqual(target.status, "To do")
        self.assertEqual(target.tone, "info")

        by_key = card.resolve([self.issue.key], self.agent)
        self.assertEqual(by_key[self.issue.key].label, target.label)

        service.move_issue(self.admin, self.issue, self.done)
        self.assertEqual(
            card.resolve([str(self.issue.pk)], self.agent)[str(self.issue.pk)].tone, "ok"
        )

        self.assertEqual(card.from_url("https://x.test/projects/NET-1/"), str(self.issue.pk))
        self.assertIsNone(card.from_url("/projects/NET/"))
        self.assertEqual([t.label for t in card.search("net-1", self.agent, 5)], [f"NET-1 {TITLE}"])
        self.assertEqual(
            [t.label for t in card.search("switch", self.agent, 5)], [f"NET-1 {TITLE}"]
        )
        self.assertEqual(card.resolve([str(self.issue.pk)], self.customer), {})

        project = get_resolver("project")
        target = project.resolve([str(self.project.pk)], self.admin)[str(self.project.pk)]
        self.assertEqual(target.label, f"NET {PROJECT_NAME}")
        self.assertEqual(target.url, "/projects/NET/")
        self.assertEqual(target.status, "Scrum")
        self.assertEqual(project.from_url("https://x.test/projects/NET/"), str(self.project.pk))
        self.assertIsNone(project.from_url("/projects/NET-1/"))
        self.assertEqual(
            [t.label for t in project.search("net", self.admin, 5)], [f"NET {PROJECT_NAME}"]
        )


class WikiChipTests(ViewTest):
    def test_wiki_card_chip_resolves(self):
        self.issue(title=TITLE, type="story")
        html = render_markdown("[[card:NET-1]]", user=self.agent)
        self.assertIn('href="/projects/NET-1/"', html)
        self.assertIn(TITLE, html)

    def test_wiki_chip_uses_the_pk_too(self):
        issue = self.issue(title=TITLE, type="story")
        html = render_markdown(f"[[card:{issue.pk}]]", user=self.agent)
        self.assertIn('href="/projects/NET-1/"', html)

    def test_customer_sees_only_the_words(self):
        self.issue(title=TITLE, type="story")
        self.assertNotIn("/projects/NET-1/", render_markdown("[[card:NET-1]]", user=self.customer))


class EventLineTests(ViewTest):
    def test_removed_from_sprint_reads_plainly(self):
        issue = self.issue(title=TITLE, type="story")
        sprint = Sprint.objects.create(project=self.project, name="Sprint 9", state="active")
        service.set_sprint(self.agent, issue, sprint)
        service.set_sprint(self.agent, issue, None)
        self.login(self.agent)
        page = self.client.get(reverse("projects:issue_detail", args=[("NET", 1)])).content.decode()
        self.assertIn("Removed from the sprint", page)
        self.assertIn("Added to Sprint 9", page)
        self.assertEqual(IssueEvent.objects.filter(issue=issue).count(), 3)

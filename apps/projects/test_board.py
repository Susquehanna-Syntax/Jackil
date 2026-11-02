"""The board screen: its columns and cards, moving a card, and Kanban WIP limits.

Kanban issue numbers start at OPS-500 so the cards here can never collide with
the NET numbers the Scrum fixtures hand out — the two projects share no rows.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from apps.projects import service
from apps.projects.models import PersonRate, Sprint
from apps.projects.test_backlog import BacklogTest


class BoardTest(BacklogTest):
    """The BacklogTest fixtures plus a Kanban board and its helpers."""

    def kanban(self, name="OPS", title="Ops board"):
        return service.create_project(self.admin, name, title, "kanban")

    def card(self, project, title, **fields):
        """A card in any project — the Scrum fixture's `issue` is NET-only."""
        return service.create_issue(self.admin, project, title=title, **fields)

    def board_data(self, key="NET", query=""):
        response = self.client.get(f"/projects/{key}/board/data/{query}")
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def columns_by_name(self, body):
        return {column["name"]: column for column in body["columns"]}

    def keys(self, column):
        return [card["key"] for card in column["issues"]]

    def move(self, key, issue, column, before=None, force=None):
        return self.client.post(
            f"/projects/{key}/board/move/",
            data=json.dumps(
                {
                    "issue": issue.id,
                    "column": column.id,
                    "before": None if before is None else before.id,
                    **({} if force is None else {"force": force}),
                }
            ),
            content_type="application/json",
        )


class BoardDataTests(BoardTest):
    def test_board_data_scrum_shows_the_active_sprint_only(self):
        active = self.sprint(
            "NET Sprint 1",
            state="active",
            start_date=date(2026, 10, 26),
            end_date=date(2026, 11, 10),
        )
        planned = self.sprint("Later sprint")
        closed = self.sprint("Old sprint", state="closed")
        card = self.issue(title="Run the board", assignee=self.agent, story_points=5)
        service.set_sprint(self.agent, card, active)
        service.move_issue(self.admin, card, self.doing)
        in_sprint = self.issue(title="Also this sprint")
        service.set_sprint(self.agent, in_sprint, active)
        elsewhere = self.issue(title="Waiting for a sprint")
        service.set_sprint(self.agent, elsewhere, planned)
        self.issue(title="Already delivered", sprint=closed, column=self.done)

        self.login(self.agent)
        body = self.board_data()
        self.assertEqual(body["method"], "scrum")
        self.assertEqual(
            body["sprint"], {"id": active.id, "name": "NET Sprint 1", "end_date": "2026-11-10"}
        )
        columns = self.columns_by_name(body)
        self.assertEqual(
            [column["id"] for column in body["columns"]],
            [self.todo.id, self.doing.id, self.done.id],
        )
        self.assertEqual(self.keys(columns["In progress"]), [card.key])
        self.assertEqual(self.keys(columns["To do"]), [in_sprint.key])
        self.assertEqual(self.keys(columns["Done"]), [])
        self.assertEqual(
            columns["In progress"]["issues"][0],
            {
                "id": card.id,
                "key": card.key,
                "title": "Run the board",
                "type": "story",
                "points": 5,
                "assignee": {
                    "id": self.agent.id,
                    "name": "aria",
                    "initials": self.agent.avatar_initials,
                    "color": "lavender",
                },
                "priority": "medium",
                "url": f"/projects/{card.key}/",
                "subtasks_done": 0,
                "subtasks_total": 0,
            },
        )
        self.assertIsNone(columns["To do"]["issues"][0]["assignee"])

    def test_board_data_without_an_active_sprint_is_empty_with_sprint_null(self):
        self.sprint("Planned sprint")
        self.issue(title="Sitting in the backlog")

        self.login(self.agent)
        body = self.board_data()
        self.assertIsNone(body["sprint"])
        for column in body["columns"]:
            self.assertEqual(column["issues"], [])
            self.assertEqual(column["count"], 0)

    def test_board_data_kanban_excludes_closed_sprints(self):
        boards = self.kanban()
        planned = Sprint.objects.create(project=boards, name="Ops Sprint 1")
        shipped = Sprint.objects.create(project=boards, name="Shipped sprint", state="closed")
        closed = self.card(boards, "Delivered last month", sprint=shipped)
        free = self.card(boards, "Nothing to do with sprints")
        queued = self.card(boards, "On a planned sprint", sprint=planned)

        self.login(self.agent)
        body = self.board_data("OPS")
        self.assertEqual(body["method"], "kanban")
        self.assertIsNone(body["sprint"])
        todo = self.columns_by_name(body)["To do"]
        self.assertEqual(self.keys(todo), [free.key, queued.key])
        self.assertNotIn(closed.key, self.keys(todo))

    def test_subtasks_are_not_cards_and_roll_up_progress(self):
        parent = self.issue(title="Rewire the annexe")
        active = self.sprint("NET Sprint 1", state="active")
        service.set_sprint(self.agent, parent, active)
        first = service.create_issue(
            self.agent, self.project, title="Pull the cable", type="subtask", parent=parent
        )
        service.create_issue(
            self.agent, self.project, title="Fit the socket", type="subtask", parent=parent
        )
        service.move_issue(self.admin, first, self.done)

        self.login(self.agent)
        body = self.board_data()
        todo = self.columns_by_name(body)["To do"]
        self.assertEqual(self.keys(todo), [parent.key])
        self.assertEqual(todo["issues"][0]["subtasks_total"], 2)
        self.assertEqual(todo["issues"][0]["subtasks_done"], 1)

    def test_issues_without_a_column_land_in_the_first_column(self):
        active = self.sprint("NET Sprint 1", state="active")
        card = self.issue(title="Column cleared by hand")
        service.set_sprint(self.agent, card, active)
        card.column = None
        card.save(update_fields=["column"])

        self.login(self.agent)
        body = self.board_data()
        columns = self.columns_by_name(body)
        self.assertEqual(self.keys(columns["To do"]), [card.key])
        self.assertEqual(columns["To do"]["count"], 1)

    def todo_keys(self, query=""):
        body = self.board_data("NET", query)
        return self.keys(self.columns_by_name(body)["To do"])

    def test_filters_assignee_me_type_q(self):
        active = self.sprint("NET Sprint 1", state="active")
        mine = self.issue(title="Route the annexe", assignee=self.agent, type="bug")
        theirs = self.issue(title="Wire the cupboard", assignee=self.admin)
        unassigned = self.issue(title="Replace the patch panel", type="task")
        for card in (mine, theirs, unassigned):
            service.set_sprint(self.agent, card, active)

        everyone = sorted([mine.key, theirs.key, unassigned.key])
        self.login(self.agent)
        self.assertEqual(self.todo_keys(f"?assignee={self.agent.id}"), [mine.key])
        self.assertEqual(self.todo_keys("?assignee=me"), [mine.key])
        self.assertEqual(self.todo_keys(f"?assignee={self.customer.id}"), [])
        self.assertEqual(sorted(self.todo_keys("?assignee=nonsense")), everyone)
        self.assertEqual(self.todo_keys("?type=bug"), [mine.key])
        self.assertEqual(sorted(self.todo_keys("?type=nonsense")), everyone)
        self.assertEqual(self.todo_keys("?q=annexe"), [mine.key])
        self.assertEqual(self.todo_keys("?assignee=me&type=task&q=route"), [])

    def test_customer_403(self):
        self.login(self.customer)
        response = self.client.get("/projects/NET/board/data/")
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            "/projects/NET/board/move/",
            data=json.dumps({"issue": 1, "column": self.doing.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_board_data_needs_a_post_for_moves(self):
        self.login(self.agent)
        response = self.client.get("/projects/NET/board/move/")
        self.assertEqual(response.status_code, 405)


class BoardMoveTests(BoardTest):
    def test_move_to_done_freezes_cost_and_out_unfreezes(self):
        PersonRate.objects.create(user=self.agent, hourly_wage=Decimal("40.00"))
        active = self.sprint("NET Sprint 1", state="active")
        card = self.issue(title="Commission the link", assignee=self.agent, story_points=3)
        service.set_sprint(self.agent, card, active)

        self.login(self.admin)
        into_done = self.move("NET", card, self.done)
        self.assertEqual(into_done.status_code, 200)
        self.assertEqual(into_done.json(), {"ok": True, "category": "done"})
        card.refresh_from_db()
        self.assertEqual(card.frozen_cost, Decimal("480.00"))
        self.assertEqual(card.completed_by, self.agent)

        back = self.move("NET", card, self.doing)
        self.assertEqual(back.status_code, 200)
        card.refresh_from_db()
        self.assertIsNone(card.frozen_cost)
        self.assertIsNone(card.completed_at)
        self.assertIsNone(card.completed_by)

    def test_move_ranks_above_the_named_card(self):
        active = self.sprint("NET Sprint 1", state="active")
        second = self.issue(title="Second in the column")
        service.set_sprint(self.agent, second, active)
        service.move_issue(self.admin, second, self.doing)
        third = self.issue(title="Coming from elsewhere")
        service.set_sprint(self.agent, third, active)

        self.login(self.agent)
        response = self.move("NET", third, self.doing, before=second)
        self.assertEqual(response.status_code, 200)
        doing = self.columns_by_name(self.board_data())["In progress"]
        self.assertEqual(self.keys(doing), [third.key, second.key])
        third.refresh_from_db()
        second.refresh_from_db()
        self.assertLess(third.rank, second.rank)

        last = self.issue(title="Straight to the end")
        service.set_sprint(self.agent, last, active)
        response = self.move("NET", last, self.doing)
        self.assertEqual(response.status_code, 200)
        doing = self.columns_by_name(self.board_data())["In progress"]
        self.assertEqual(self.keys(doing), [third.key, second.key, last.key])

    def test_move_needs_both_ends_in_the_project(self):
        boards = self.kanban()
        other = self.card(boards, "Another project's board")
        card = self.issue(title="Mine to move")
        foreign_card = self.card(boards, "Not mine either")

        self.login(self.admin)
        self.assertEqual(self.move("NET", card, other.column).status_code, 404)
        self.assertEqual(self.move("NET", foreign_card, self.doing).status_code, 404)

    def test_move_before_a_card_in_another_column_is_400(self):
        active = self.sprint("NET Sprint 1", state="active")
        card = self.issue(title="Moving this one")
        neighbour = self.issue(title="Sitting in another column")
        for item in (card, neighbour):
            service.set_sprint(self.agent, item, active)
        service.move_issue(self.admin, neighbour, self.done)

        self.login(self.agent)
        response = self.move("NET", card, self.doing, before=neighbour)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        card.refresh_from_db()
        self.assertNotEqual(card.column_id, self.doing.id)

    def test_subtask_cannot_be_moved(self):
        parent = self.issue(title="Parent story")
        child = service.create_issue(
            self.agent, self.project, title="Crimp the lead", type="subtask", parent=parent
        )

        self.login(self.agent)
        response = self.move("NET", child, self.doing)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Sub-tasks move with their parent's card.")
        child.refresh_from_db()
        self.assertNotEqual(child.column_id, self.doing.id)

    def test_wip_limit_returns_409_unless_forced(self):
        boards = self.kanban()
        doing = boards.columns.get(category="in_progress")
        todo = boards.columns.get(category="todo")
        doing.wip_limit = 3
        doing.save(update_fields=["wip_limit"])
        holding = [self.card(boards, f"Work in progress {number}") for number in range(3)]
        for card in holding:
            service.move_issue(self.admin, card, doing)
        waiting = self.card(boards, "Waiting for a slot")

        self.login(self.admin)
        response = self.move("OPS", waiting, doing)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(), {"error": "In progress is at its limit of 3.", "wip": True}
        )
        waiting.refresh_from_db()
        self.assertNotEqual(waiting.column_id, doing.id)

        self.assertEqual(self.move("OPS", holding[0], todo).status_code, 200)
        self.assertEqual(self.move("OPS", waiting, doing).status_code, 200)
        waiting.refresh_from_db()
        self.assertEqual(waiting.column, doing)

        self.assertEqual(self.move("OPS", holding[1], doing, force=True).status_code, 200)

    def test_scrum_ignores_wip_limits(self):
        self.doing.wip_limit = 1
        self.doing.save(update_fields=["wip_limit"])
        active = self.sprint("NET Sprint 1", state="active")
        first = self.issue(title="First in progress")
        second = self.issue(title="Second in progress")
        for card in (first, second):
            service.set_sprint(self.agent, card, active)
        service.move_issue(self.admin, first, self.doing)

        self.login(self.agent)
        response = self.move("NET", second, self.doing)
        self.assertEqual(response.status_code, 200)
        second.refresh_from_db()
        self.assertEqual(second.column, self.doing)


class BoardPageTests(BoardTest):
    def test_kanban_backlog_redirects_to_the_board(self):
        boards = service.create_project(self.admin, "BRD", "Board Room", "kanban")
        self.login(self.agent)
        response = self.client.get(reverse("projects:backlog", args=[boards.key]))
        self.assertRedirects(response, reverse("projects:board", args=[boards.key]))

    def test_board_page_renders_for_both_methods(self):
        boards = self.kanban()
        self.login(self.agent)
        scrum = self.client.get(reverse("projects:board", args=["NET"]))
        kanban = self.client.get(reverse("projects:board", args=[boards.key]))
        self.assertEqual(scrum.status_code, 200)
        self.assertEqual(kanban.status_code, 200)
        for response, key, data_url in (
            (scrum, "NET", "/projects/NET/board/data/"),
            (kanban, "OPS", "/projects/OPS/board/data/"),
        ):
            page = response.content.decode()
            self.assertIn('id="bd-columns"', page)
            self.assertIn(data_url, page)
            self.assertIn("jackil-board.js", page)
            self.assertIn(f"{key} Board — Projects — Jackil", page)
        self.assertIn(reverse("projects:backlog", args=["NET"]), scrum.content.decode())
        self.assertNotIn(reverse("projects:backlog", args=["OPS"]), kanban.content.decode())

    def test_project_page_links_the_board(self):
        boards = self.kanban()
        self.login(self.agent)
        for key in ("NET", boards.key):
            page = self.client.get(reverse("projects:project_detail", args=[key])).content.decode()
            self.assertIn(reverse("projects:board", args=[key]), page)

    def test_the_board_page_is_staff_only(self):
        self.kanban()
        self.login(self.customer)
        self.assertEqual(self.client.get("/projects/OPS/board/").status_code, 403)

    def test_anonymous_is_sent_to_sign_in(self):
        response = self.client.get("/projects/NET/board/data/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)


class BoardScriptTests(SimpleTestCase):
    def setUp(self):
        self.script = Path(settings.BASE_DIR, "static/js/jackil-board.js").read_text()

    def test_script_wires_the_drag_and_the_dialogs(self):
        for literal in [
            "'dragstart'",
            "'drop'",
            "'dragover'",
            "data-issue-id",
            "closest('.bd-card')",
            "data-move-url",
            "status === 409",
            "force: true",
            "data-bd-move",
            "bd-move-modal",
            "escHtml",
            "showToast",
        ]:
            self.assertIn(literal, self.script)

    def test_script_has_no_side_stripes(self):
        self.assertNotIn("border-left", self.script)

    def test_board_css_has_no_side_stripes(self):
        css = Path(settings.BASE_DIR, "static/css/style.css").read_text()
        block = css.split("/* Board (M5 p04b) */", 1)[1]
        self.assertNotIn("border-left", block)
        self.assertNotIn("border-right", block)

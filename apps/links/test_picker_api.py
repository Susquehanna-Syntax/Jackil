"""The picker endpoints: tabs, per-type search, recent results and previews."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.items.models import Item, ItemKind
from apps.links import registry
from apps.links.registry import LinkTarget, Resolver, picker_types, register_type
from apps.links.service import add_link
from apps.projects import service as projects_service
from apps.tickets.models import Ticket
from apps.vigil import links as vigil_links
from apps.vigil.client import VigilUnavailable
from apps.wiki.models import Page, Space

#: Titles nothing else in the test database uses.
PRINTER = "Printer tray two jams"


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class BareResolver(Resolver):
    def resolve(self, ids, user):
        return {i: LinkTarget(type="bare:thing", id=i, label=i) for i in ids}


class PickerOrderTests(TestCase):
    """The registry's own contract, with a type no milestone has registered."""

    def test_unregistered_extras_come_after_the_tabs_in_alphabetical_order(self):
        register_type("temp:zed", BareResolver())
        register_type("temp:aleph", BareResolver())
        try:
            names = picker_types()
            colours = {name: registry.type_colour(name) for name in names}
        finally:
            registry._TYPES.pop("temp:zed", None)
            registry._TYPES.pop("temp:aleph", None)

        tabbed = [name for name in names if name != "vigil:device"]
        self.assertEqual(tabbed[:6], ["vigil:host", "ticket", "page", "card", "project", "item"])
        tail = [name for name in tabbed[6:] if name.startswith("temp:")]
        self.assertEqual(tail, ["temp:aleph", "temp:zed"])
        self.assertLess(names.index("vigil:host"), names.index("item"))
        self.assertEqual(colours["temp:zed"], "all")


class PickerApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.agent = make_user("aria", "agent")
        self.admin = make_user("coral", "admin")
        self.customer = make_user("boa", "customer")
        self.space = Space.objects.create(name="Support")
        self.server = ItemKind.objects.get(name="Server")
        self.printer_ticket = Ticket.objects.create(
            title=PRINTER, description="body", created_by=self.agent, priority="high"
        )
        self.page = Page.objects.create(
            title="Printer care",
            space=self.space,
            body="# Title\n\nRestart the **spooler** now.",
            is_published_to_help_center=True,
        )

    def _get(self, user, name, *args, **query):
        self.client.force_login(user)
        url = reverse(name, args=args)
        if query:
            url = url + "?" + "&".join(f"{k}={v}" for k, v in query.items())
        return self.client.get(url)

    def touch(self, *tickets):
        """Move the given tickets to the end of the updated-at order."""
        for ticket in tickets:
            ticket.save()

    def test_types_lists_picker_order_with_colours(self):
        body = self._get(self.agent, "links:links-types").json()
        names = [row["name"] for row in body["types"]]
        rows = {row["name"]: row for row in body["types"]}

        self.assertLess(names.index("ticket"), names.index("page"))
        self.assertLess(names.index("page"), names.index("item"))
        self.assertEqual(rows["ticket"]["colour"], "rose")
        self.assertEqual(rows["item"]["label"], "Dynamic Items")
        self.assertTrue(rows["ticket"]["available"])

    def test_search_by_type_returns_only_that_type(self):
        Page.objects.create(title="Printer firmware", space=self.space, body="b")
        body = self._get(self.agent, "links:links-search", type="ticket", q="printer").json()

        self.assertTrue(body["available"])
        self.assertEqual([row["type"] for row in body["results"]], ["ticket"])
        self.assertEqual(body["results"][0]["label"], f"#{self.printer_ticket.pk} {PRINTER}")

    def test_empty_query_with_type_returns_recent(self):
        older = Ticket.objects.create(title="Desk phone", description="body", created_by=self.agent)
        newest = Ticket.objects.create(
            title="Wifi drops", description="body", created_by=self.agent
        )
        self.touch(older, newest)

        body = self._get(self.agent, "links:links-search", type="ticket").json()

        self.assertTrue(body["available"])
        self.assertEqual(
            [row["id"] for row in body["results"][:2]], [str(newest.pk), str(older.pk)]
        )

    def test_unknown_type_is_400(self):
        response = self._get(self.agent, "links:links-search", type="nothing", q="printer")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Unknown type."})

    def test_preview_ticket_has_facts_and_links(self):
        add_link(
            self.agent,
            ("ticket", str(self.printer_ticket.pk)),
            ("page", str(self.page.pk)),
        )
        body = self._get(
            self.agent, "links:links-preview", "ticket", str(self.printer_ticket.pk)
        ).json()

        facts = body["target"]["facts"]
        self.assertIn(["Priority", "High"], facts)
        self.assertIn(["Assignee", "Unassigned"], facts)
        self.assertEqual(body["target"]["type_label"], "Tickets")
        self.assertEqual(body["target"]["colour"], "rose")
        self.assertEqual(len(body["links"]), 1)
        self.assertEqual(body["links"][0]["other"]["label"], "Printer care")

    def test_preview_page_has_plain_excerpt(self):
        body = self._get(self.agent, "links:links-preview", "page", str(self.page.pk)).json()

        self.assertEqual(body["target"]["excerpt"], "Title Restart the spooler now.")
        self.assertIn(["Space", "Support"], body["target"]["facts"])

    def test_preview_hidden_ticket_is_404(self):
        # Every agent may see every ticket, so the one an agent cannot resolve
        # is a ticket that isn't there: an id whose object was deleted.
        with patch("apps.links.builtin._visible", return_value=False):
            response = self._get(
                self.agent, "links:links-preview", "ticket", str(self.printer_ticket.pk)
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Not found."})

    def test_preview_unknown_type_is_404(self):
        response = self._get(self.agent, "links:links-preview", "nothing", "1")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Not found."})

    def test_customer_cannot_use_picker_endpoints(self):
        self.assertEqual(self._get(self.customer, "links:links-types").status_code, 403)
        self.assertEqual(
            self._get(self.customer, "links:links-search", type="ticket").status_code, 403
        )
        self.assertEqual(
            self._get(
                self.customer, "links:links-preview", "ticket", str(self.printer_ticket.pk)
            ).status_code,
            403,
        )

    def test_preview_item_card_and_project_facts(self):
        item = Item.objects.create(name="Print server", kind=self.server)
        project = projects_service.create_project(self.admin, "NET", "Field Networking")
        issue = projects_service.create_issue(
            self.admin, project, title="Reimage a printer", type="story"
        )

        item_facts = self._get(self.agent, "links:links-preview", "item", str(item.pk)).json()[
            "target"
        ]["facts"]
        self.assertIn(["Vendor", "None"], item_facts)
        self.assertIn(["Warranty ends", "Not set"], item_facts)
        self.assertIn(["Owner", "No owner"], item_facts)

        card = self._get(self.agent, "links:links-preview", "card", str(issue.pk)).json()["target"]
        self.assertEqual(card["type_label"], "Issues")
        card_facts = card["facts"]
        self.assertIn(["Assignee", "Unassigned"], card_facts)
        self.assertIn(["Sprint", "Backlog"], card_facts)
        self.assertIn(["Points", "Not estimated"], card_facts)

        project_facts = self._get(
            self.agent, "links:links-preview", "project", str(project.pk)
        ).json()["target"]["facts"]
        self.assertIn(["Lead", "No lead"], project_facts)
        self.assertIn(["Key", "NET"], project_facts)

    def test_recent_pages_and_search_of_the_whole_board_are_unchanged(self):
        # The old panel keeps its response shape, and a page tab lists what
        # was edited last.
        older = Page.objects.create(title="Boot order", space=self.space, body="b")
        newest = Page.objects.create(title="Toner order", space=self.space, body="b")
        older.save()
        newest.save()

        recent = self._get(self.agent, "links:links-search", type="page").json()["results"]
        self.assertEqual([row["id"] for row in recent[:2]], [str(newest.pk), str(older.pk)])

        whole_board = self._get(self.agent, "links:links-search", q="printer").json()
        self.assertEqual(set(whole_board), {"results"})
        self.assertIn("page", {row["type"] for row in whole_board["results"]})

    def test_tab_with_nothing_to_show_is_an_empty_list(self):
        register_type("temp:nowhere", BareResolver())
        try:
            body = self._get(self.agent, "links:links-search", type="temp:nowhere").json()
        finally:
            registry._TYPES.pop("temp:nowhere", None)

        self.assertTrue(body["available"])
        self.assertEqual(body["results"], [])


class VigilDownTests(TestCase):
    """Review Focus 1: one tab whose source is down does not take the others."""

    def setUp(self):
        cache.clear()
        self.agent = make_user("aria", "agent")
        self.customer = make_user("boa", "customer")
        self.printer_ticket = Ticket.objects.create(
            title=PRINTER, description="body", created_by=self.agent
        )

    def test_vigil_down_marks_vigil_tabs_unavailable_others_work(self):
        fake = FakeVigilClient()
        with patch.object(vigil_links, "get_client", return_value=fake):
            cache.set(vigil_links.DOWN_KEY, "down", 60)

            body = self._get(self.agent, "links:links-types").json()
            rows = {row["name"]: row for row in body["types"]}
            self.assertFalse(rows["vigil:host"]["available"])
            self.assertTrue(rows["ticket"]["available"])

            down = self._get(self.agent, "links:links-search", type="vigil:host", q="web").json()
            self.assertEqual(down, {"available": False, "results": []})

            working = self._get(self.agent, "links:links-search", type="ticket", q="printer").json()
            self.assertTrue(working["available"])
            self.assertEqual(
                [row["id"] for row in working["results"]], [str(self.printer_ticket.pk)]
            )

    def test_vigil_preview_carries_facts(self):
        fake = FakeVigilClient(
            detail={
                "label": "web-01",
                "url": "http://v/h/1",
                "status": "Online",
                "tone": "ok",
                "facts": [["OS", "Ubuntu"], ["bad"], ["IP", "10.0.0.5"]],
            }
        )
        with patch.object(vigil_links, "get_client", return_value=fake):
            body = self._get(self.agent, "links:links-preview", "vigil:host", "1").json()

        self.assertEqual(body["target"]["facts"], [["OS", "Ubuntu"], ["IP", "10.0.0.5"]])
        self.assertEqual(body["target"]["label"], "web-01")
        self.assertEqual(fake.detail_calls, [("host", "1")])

    def test_vigil_preview_when_down_says_so_stops_calling_and_lets_others_work(self):
        message = "Can't reach Vigil at vigil.example.gov."
        fake = FakeVigilClient(
            detail=VigilUnavailable(message),
            items=VigilUnavailable(message),
        )
        with patch.object(vigil_links, "get_client", return_value=fake):
            first = self._get(self.agent, "links:links-preview", "vigil:host", "1").json()

            body = self._get(self.agent, "links:links-types").json()
            rows = {row["name"]: row for row in body["types"]}
            self.assertFalse(rows["vigil:host"]["available"])
            self.assertTrue(rows["ticket"]["available"])

            down = self._get(self.agent, "links:links-search", type="vigil:host", q="web").json()
            self.assertEqual(down, {"available": False, "results": []})

            working = self._get(self.agent, "links:links-search", type="ticket", q="printer").json()
            self.assertTrue(working["available"])
            self.assertEqual(
                [row["id"] for row in working["results"]], [str(self.printer_ticket.pk)]
            )

            second = self._get(self.agent, "links:links-preview", "vigil:host", "1").json()

        for target in (first["target"], second["target"]):
            self.assertFalse(target["available"])
            self.assertEqual(target["status"], "Vigil unavailable")
        self.assertEqual(cache.get(vigil_links.DOWN_KEY), message)
        self.assertEqual(
            fake.detail_calls,
            [("host", "1")],
            "the second preview must not reach Vigil again",
        )

    def _get(self, user, name, *args, **query):
        self.client.force_login(user)
        url = reverse(name, args=args)
        if query:
            url = url + "?" + "&".join(f"{k}={v}" for k, v in query.items())
        return self.client.get(url)


class FakeVigilClient:
    """Only the calls a picker tab makes."""

    def __init__(self, detail=None, items=None):
        self.detail_result = detail
        self.items = items if items is not None else {}
        self.detail_calls = []
        self.resolve_calls = []

    def detail(self, type, id):
        self.detail_calls.append((type, id))
        if isinstance(self.detail_result, Exception):
            raise self.detail_result
        return self.detail_result

    def resolve(self, type, ids):
        self.resolve_calls.append((type, list(ids)))
        if isinstance(self.items, Exception):
            raise self.items
        return {i: self.items[i] for i in ids if i in self.items}

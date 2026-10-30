"""The links panel: the shell on ticket and item pages, and what fills it."""

import re
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.items.models import Item, ItemKind
from apps.links.service import add_link
from apps.tickets.models import Ticket

ROOT = Path(__file__).resolve().parents[2]

#: The forbidden words live as fragments so this file can't trip its own check.
FORBIDDEN = re.compile("C" + "MDB|" + r"\bC" + "Is?\b")


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class LinksPanelTests(TestCase):
    def setUp(self):
        self.agent = make_user("aria", "agent")
        self.customer = make_user("boa", "customer")
        self.server = ItemKind.objects.get(name="Server")
        self.ticket = Ticket.objects.create(
            title="Mail is bouncing", description="body", created_by=self.customer
        )
        self.item = Item.objects.create(name="Mail server", kind=self.server)

    def test_ticket_page_shows_panel_for_agent(self):
        self.client.force_login(self.agent)
        body = self.client.get(
            reverse("tickets:ticket_detail", args=[self.ticket.pk])
        ).content.decode()
        self.assertIn("data-links-panel", body)
        self.assertIn('data-type="ticket"', body)
        self.assertIn(f'data-id="{self.ticket.pk}"', body)
        self.assertIn("js/jackil-links.js", body)

    def test_ticket_page_hides_panel_for_customer(self):
        self.client.force_login(self.customer)
        body = self.client.get(
            reverse("tickets:ticket_detail", args=[self.ticket.pk])
        ).content.decode()
        self.assertNotIn("data-links-panel", body)

    def test_item_page_shows_panel(self):
        self.client.force_login(self.agent)
        body = self.client.get(reverse("items:item_detail", args=[self.item.pk])).content.decode()
        self.assertIn("data-links-panel", body)
        self.assertIn('data-type="item"', body)
        self.assertNotIn('id="links-panel"', body)

    def test_a_linked_target_reaches_the_panel_as_a_chip(self):
        add_link(
            self.agent,
            ("ticket", str(self.ticket.pk)),
            ("item", str(self.item.pk)),
            "blocks",
        )
        self.client.force_login(self.agent)
        body = self.client.get(
            reverse("links:links-for", args=["ticket", str(self.ticket.pk)])
        ).content.decode()
        self.assertIn('"relation":"blocks"', body)
        self.assertIn('"label":"Mail server"', body)


class LinksScriptTests(SimpleTestCase):
    def test_links_js_escapes(self):
        script = read("static", "js", "jackil-links.js")
        self.assertGreaterEqual(script.count("escHtml("), 4)
        # Every string from the server reaches the page escaped, so nothing
        # concatenates or interpolates a bare `label`.
        self.assertNotIn("${label}", script)
        self.assertNotIn("+ label", script)
        self.assertIn("escHtml(label)", script)  # the group heading

    def test_panel_css_is_present(self):
        css = read("static", "css", "style.css")
        for rule in (".links-panel", ".links-group-chips", ".link-chip-status", ".links-result"):
            with self.subTest(rule=rule):
                self.assertIn(rule, css)

    def test_panel_shell_and_script_agree_on_their_markers(self):
        shell = read("apps", "links", "templates", "links", "panel.html")
        script = read("static", "js", "jackil-links.js")
        for marker in ("data-links-panel", "data-links-groups", "data-links-add"):
            with self.subTest(marker=marker):
                self.assertIn(marker, shell)
                self.assertIn(marker, script)

    def test_result_rows_carry_the_marker_the_click_handler_looks_for(self):
        # The dialog's click handler finds rows with closest('[data-links-result]');
        # rows were once rendered without it, so picking a result did nothing.
        script = read("static", "js", "jackil-links.js")
        self.assertIn("closest('[data-links-result]')", script)
        self.assertRegex(script, r'class="links-result[^"]*[^>]*data-links-result')

    def test_base_page_loads_the_script_after_the_modal(self):
        base = read("templates", "base.html")
        self.assertLess(base.index("jackil-modal.js"), base.index("jackil-links.js"))

    def test_no_forbidden_words(self):
        checked = [
            path
            for path in Path(__file__).resolve().parent.rglob("*.py")
            if "migrations" not in path.parts and "test" not in path.name
        ]
        checked.append(ROOT / "static" / "js" / "jackil-links.js")
        self.assertGreater(len(checked), 4)
        for path in checked:
            with self.subTest(path=path.name):
                self.assertIsNone(
                    FORBIDDEN.search(path.read_text(encoding="utf-8")),
                    f"{path.name} names the feature wrongly",
                )

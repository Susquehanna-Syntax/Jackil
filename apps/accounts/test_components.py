from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.tickets.models import Ticket


class ComponentStylesTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (Path(settings.BASE_DIR) / "static/css/style.css").read_text()

    def test_tint_and_component_rules_present(self):
        for selector in [
            ".tint {",
            ".tc-coral {",
            ".btn-tint {",
            ".btn-coral {",
            ".pill {",
            ".chip {",
            ".toggle {",
            ".tab-bar {",
            ".alert-item {",
        ]:
            self.assertIn(selector, self.css)

    def test_no_filled_button_rules(self):
        self.assertNotIn("btn-filled-", self.css)

    def test_tags_use_tokens(self):
        for literal in [
            "rgba(240,144,128,0.12)",
            "rgba(126,221,181,0.12)",
            "rgba(186,168,232,0.08)",
        ]:
            self.assertNotIn(literal, self.css)
        self.assertIn(
            ".tag-critical { color: var(--coral-ink); "
            "background: rgba(var(--rgb-coral), var(--tint-a)); }",
            self.css,
        )


class TemplateClassTests(SimpleTestCase):
    def test_no_template_uses_filled_buttons(self):
        base = Path(settings.BASE_DIR)
        roots = [base / "templates", *sorted((base / "apps").glob("*/templates"))]
        seen = 0
        for root in roots:
            for path in root.rglob("*.html"):
                seen += 1
                self.assertNotIn("btn-filled-", path.read_text(), str(path))
        self.assertGreater(seen, 0)


class ModalWiringTests(TestCase):
    def setUp(self):
        self.agent = User.objects.create_user("aria", "aria@x.com", "password123", role="agent")
        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.agent)

    def test_ticket_page_uses_shared_modal(self):
        ticket = Ticket.objects.create(title="T", description="D", created_by=self.agent)
        res = self.client.get(reverse("tickets:ticket_detail", args=[ticket.pk]))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn("js/jackil-modal.js", html)
        self.assertIn("JackilModal.open('manage_modal'", html)
        self.assertIn('id="manage_modal"', html)

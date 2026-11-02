from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User


class ShellTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("aria", "aria@x.com", "password123", role="agent")
        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.user)

    def test_agent_page_has_sidebar_controls(self):
        res = self.client.get(reverse("tickets:dashboard"))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn('id="sidebar-toggle"', html)
        self.assertIn('id="theme-toggle"', html)
        self.assertIn("js/jackil-ui.js", html)

    def test_customer_page_has_sidebar_controls(self):
        customer = User.objects.create_user("bo", "bo@x.com", "password123", role="customer")
        self.client.force_login(customer)
        res = self.client.get(reverse("tickets:customer_tickets"))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn('id="sidebar-toggle"', html)
        self.assertNotIn(">Customer<", html)

    def test_prepaint_script_on_login_page(self):
        res = Client(SERVER_NAME="localhost").get(reverse("accounts:login"))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn("sqsy-theme", html)
        self.assertIn("jackil-sidebar", html)
        self.assertIn("IBM+Plex+Mono", html)


class StylesheetTokenTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (Path(settings.BASE_DIR) / "static/css/style.css").read_text()

    def test_four_themes_present(self):
        self.assertIn(':root[data-theme="light"]', self.css)
        self.assertIn(':root[data-theme="river"]', self.css)
        self.assertIn(':root[data-theme="ink"]', self.css)
        self.assertIn("--brand: var(--coral);", self.css)

    def test_no_hardcoded_sidebar_chrome(self):
        # The Dark theme's --glass token is rgba(28, 28, 33, 0.78) itself, so
        # that literal is only forbidden inside the .sidebar rule.
        start = self.css.index("\n.sidebar {")
        sidebar_rule = self.css[start : self.css.index("}", start)]
        self.assertNotIn("rgba(28, 28, 33, 0.78)", sidebar_rule)
        self.assertIn("var(--glass)", sidebar_rule)
        for literal in (
            "rgba(255,255,255,0.04)",
            "rgba(255,255,255,0.06)",
            "color: var(--bg);",
        ):
            self.assertNotIn(literal, self.css)

    def test_expandable_sidebar_rules(self):
        self.assertIn(':root[data-sidebar="expanded"] .sidebar {', self.css)
        self.assertIn(".sidebar-label { display: none; }", self.css)

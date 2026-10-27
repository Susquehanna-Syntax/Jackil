from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User


class AppearanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("aria", "aria@x.com", "password123", role="agent")
        self.client = Client(SERVER_NAME="localhost")
        self.client.force_login(self.user)

    def test_profile_has_four_theme_cards(self):
        res = self.client.get(reverse("accounts:profile"))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        for mode in ("dark", "light", "river", "ink"):
            self.assertIn(f'data-theme-set="{mode}"', html)
        self.assertIn('id="follow-system"', html)
        self.assertIn("data-rm-toggle", html)

    def test_appearance_card_is_outside_forms(self):
        html = self.client.get(reverse("accounts:profile")).content.decode()
        tail = html[html.index('id="appearance"') :]
        self.assertNotIn("<form", tail)

    def test_prepaint_reads_reduce_motion(self):
        html = self.client.get(reverse("accounts:profile")).content.decode()
        self.assertIn("jackil-reduce-motion", html)

    def test_settings_nav_is_tinted(self):
        admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")
        self.client.force_login(admin)
        res = self.client.get(reverse("console:settings_home"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("settings-nav-item tc-lav", res.content.decode())


class AppearanceStylesTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (Path(settings.BASE_DIR) / "static/css/style.css").read_text()

    def test_theme_card_and_motion_rules(self):
        self.assertIn(".theme-card {", self.css)
        self.assertIn(".set-row {", self.css)
        self.assertIn("html.rm-sim *", self.css)
        self.assertNotIn("rgba(240,184,136,0.12)", self.css)

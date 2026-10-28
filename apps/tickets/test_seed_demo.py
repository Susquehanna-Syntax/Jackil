from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import User
from apps.items.models import Item
from apps.links.models import DynamicLink
from apps.tickets.management.commands.seed_demo import RUNBOOK
from apps.wiki.markdown import render
from apps.wiki.models import Page, Space


class SeedDemoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="seed-admin", password="x", role="admin", email="seed-admin@example.com"
        )

    def test_seed_creates_items_pages_and_links(self):
        call_command("seed_demo", stdout=StringIO())

        self.assertGreaterEqual(Item.objects.count(), 8)
        self.assertTrue(
            {"Servers", "Networking", "Onboarding", "Help Center"}.issubset(
                set(Space.objects.values_list("name", flat=True))
            )
        )
        runbook = Page.objects.filter(space__name="Servers", title="Mail relay runbook").first()
        self.assertIsNotNone(runbook)
        self.assertTrue(runbook.versions.exists())
        self.assertGreaterEqual(DynamicLink.objects.count(), 4)

    def test_seed_is_idempotent_for_items_pages_and_links(self):
        call_command("seed_demo", stdout=StringIO())
        before = (Item.objects.count(), Page.objects.count(), DynamicLink.objects.count())
        call_command("seed_demo", stdout=StringIO())
        after = (Item.objects.count(), Page.objects.count(), DynamicLink.objects.count())
        self.assertEqual(before, after)

    def test_runbook_renders_math_and_a_callout(self):
        body = RUNBOOK.replace("MAIL_TICKET_ID", "1")
        html = str(render(body, user=self.admin))
        self.assertIn("math inline", html)
        self.assertIn("math block", html)
        self.assertIn("markdown-alert-warning", html)

    def test_seed_data_is_fictional(self):
        call_command("seed_demo", stdout=StringIO())
        for item in Item.objects.all():
            for value in item.attributes.values():
                self._fictional(str(value))
        for page in Page.objects.all():
            self._fictional(page.body)

    @staticmethod
    def _fictional(text):
        lowered = text.lower().replace("example.com", "")
        assert ".com" not in lowered, text

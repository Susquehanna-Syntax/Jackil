import re
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import User
from apps.items.models import Item
from apps.links.models import DynamicLink
from apps.portals.models import Portal
from apps.projects.metrics import velocity_chart
from apps.projects.models import Issue, Project, Sprint
from apps.tickets.management.commands.seed_demo import RUNBOOK
from apps.wiki.markdown import render
from apps.wiki.models import Page, Space


class SeedDemoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="seed-admin", password="x", role="admin", email="seed-admin@example.com"
        )

    def test_seed_creates_items_pages_and_links(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)

        summary = out.getvalue().splitlines()[-1]
        self.assertRegex(
            summary,
            r"\d+ departments, \d+ users, \d+ tickets, \d+ items, \d+ pages, "
            r"\d+ links, \d+ projects, \d+ issues\.",
        )
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

    def test_seed_creates_projects_with_velocity_history(self):
        call_command("seed_demo", stdout=StringIO())

        ops = Project.objects.filter(key="OPS").first()
        web = Project.objects.filter(key="WEB").first()
        self.assertIsNotNone(ops)
        self.assertIsNotNone(web)

        self.assertEqual(ops.sprints.filter(state="closed").count(), 3)
        self.assertEqual(ops.sprints.filter(state="active").count(), 1)
        self.assertEqual(web.sprints.count(), 0)

        chart = velocity_chart(ops)
        completed = next(s["values"] for s in chart["series"] if s["name"] == "Completed")
        self.assertEqual(len(completed), 3)
        for points in completed:
            self.assertGreater(points, 0)

    def test_seed_publishes_the_it_support_portal(self):
        call_command("seed_demo", stdout=StringIO())

        portal = Portal.objects.filter(slug="it-support").first()
        self.assertIsNotNone(portal)
        self.assertTrue(portal.is_published)
        self.assertEqual(portal.department.name, "IT Support")

    def test_seed_is_idempotent_for_projects_and_portal(self):
        call_command("seed_demo", stdout=StringIO())
        before = (
            Project.objects.count(),
            Issue.objects.count(),
            Sprint.objects.count(),
            Portal.objects.count(),
        )
        call_command("seed_demo", stdout=StringIO())
        after = (
            Project.objects.count(),
            Issue.objects.count(),
            Sprint.objects.count(),
            Portal.objects.count(),
        )
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
        for issue in Issue.objects.all():
            self._fictional(issue.title)
            self._fictional(issue.description)

    @staticmethod
    def _fictional(text):
        # Jackil's prose speaks of "the company" and "example.com"; a seeded
        # string naming a real one, or a public address, is not demo data.
        lowered = text.lower()
        assert "ltd" not in lowered, text
        assert " inc." not in lowered, text
        assert ".co.uk" not in lowered, text
        assert not re.search(r"\b(?!example)\w+\.com\b", lowered), text

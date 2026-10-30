"""The demo seed's projects and portal: what they must look like, twice over."""

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

SUMMARY = re.compile(
    r"\d+ departments, \d+ users, \d+ tickets, \d+ items, \d+ pages, "
    r"\d+ links, \d+ projects, \d+ issues\."
)


class SeedDemoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="seed-admin", password="x", role="admin", email="seed-admin@example.com"
        )

    def test_seed_creates_items_pages_and_links(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)

        summary = out.getvalue().splitlines()[-1]
        self.assertRegex(summary, SUMMARY)
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
        completed = next(
            series["values"] for series in chart["series"] if series["name"] == "Completed"
        )
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
        before = self._counts()
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(before, self._counts())

    @staticmethod
    def _counts():
        return (
            Project.objects.count(),
            Issue.objects.count(),
            Sprint.objects.count(),
            Portal.objects.count(),
        )

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
        # Jackil's demo prose names only "the company" and example.com; anything
        # else with a real-looking domain, or a registered company suffix, is
        # a real name that has no business being in the screenshots.
        lowered = text.lower()
        assert "ltd" not in lowered, text
        assert " inc." not in lowered, text
        assert ".co.uk" not in lowered, text
        assert not re.search(r"\b(?!example)\w+\.com\b", lowered), text


class SeedUxPassTests(TestCase):
    """M18: the demo shows page owners, Needs attention, and pinned forms."""

    def test_seed_pins_forms_and_gives_pages_owners(self):
        from apps.portals.models import Portal
        from apps.wiki.models import Page

        call_command("seed_demo", stdout=StringIO())
        portal = Portal.objects.get(slug="it-support")
        self.assertEqual(len(portal.request_forms), 2)
        self.assertTrue(portal.space_order)
        self.assertTrue(Page.objects.filter(owner__isnull=False).exists())
        self.assertTrue(
            Page.objects.filter(title="Firewall change process", owner__isnull=True).exists()
        )

    def test_rearranged_pins_survive_a_second_seed(self):
        from apps.portals.models import Portal

        call_command("seed_demo", stdout=StringIO())
        portal = Portal.objects.get(slug="it-support")
        rearranged = portal.request_forms[::-1]
        portal.request_forms = rearranged
        portal.save()
        call_command("seed_demo", stdout=StringIO())
        portal.refresh_from_db()
        self.assertEqual(portal.request_forms, rearranged)

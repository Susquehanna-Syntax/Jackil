from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.links.registry import get_resolver, types
from apps.wiki.models import Page, PageTemplate, Space
from apps.wiki.service import save_version


class SpaceTest(TestCase):
    def test_space_slug_is_filled_from_its_name(self):
        space = Space.objects.create(name="IT Operations")
        self.assertEqual(space.slug, "it-operations")


class PageTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.space = Space.objects.create(name="Ops")
        cls.other = Space.objects.create(name="Other")

    def test_page_slug_is_unique_site_wide(self):
        first = Page.objects.create(space=self.space, title="Reset a password")
        second = Page.objects.create(space=self.other, title="Reset a password")
        self.assertEqual(first.slug, "reset-a-password")
        self.assertEqual(second.slug, "reset-a-password-2")

    def test_slug_survives_a_title_change(self):
        page = Page.objects.create(space=self.space, title="Old")
        page.title = "New"
        page.save()
        self.assertEqual(page.slug, "old")

    def test_parent_must_be_in_the_same_space(self):
        parent = Page.objects.create(space=self.space, title="Parent")
        child = Page(space=self.other, title="Child", parent=parent)
        with self.assertRaises(ValidationError):
            child.clean()

    def test_parent_cannot_be_a_descendant(self):
        root = Page.objects.create(space=self.space, title="Root")
        middle = Page.objects.create(space=self.space, title="Middle", parent=root)
        leaf = Page.objects.create(space=self.space, title="Leaf", parent=middle)

        leaf.parent = leaf
        with self.assertRaises(ValidationError):
            leaf.clean()

        root.parent = leaf
        with self.assertRaises(ValidationError):
            root.clean()

    def test_ancestors_are_root_first(self):
        root = Page.objects.create(space=self.space, title="Root")
        middle = Page.objects.create(space=self.space, title="Middle", parent=root)
        leaf = Page.objects.create(space=self.space, title="Leaf", parent=middle)

        self.assertEqual([p.pk for p in leaf.ancestors()], [root.pk, middle.pk])
        self.assertEqual(root.ancestors(), [])
        self.assertEqual(root.descendant_ids(), {middle.pk, leaf.pk})
        self.assertEqual(middle.descendant_ids(), {leaf.pk})
        self.assertEqual(leaf.descendant_ids(), set())

    def test_get_absolute_url(self):
        page = Page.objects.create(space=self.space, title="Runbook")
        self.assertEqual(page.get_absolute_url(), reverse("wiki:page_detail", args=[page.slug]))


class PageVersionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.space = Space.objects.create(name="Ops")
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")

    def test_save_version_numbers_increase(self):
        page = Page.objects.create(space=self.space, title="Runbook", body="v1")
        first = save_version(page, self.agent, summary="created")
        page.body = "v2"
        page.save()
        second = save_version(page, self.agent, summary="fixed the steps")

        self.assertEqual(first.number, 1)
        self.assertEqual(second.number, 2)
        self.assertEqual(first.body, "v1")
        self.assertEqual(second.body, "v2")
        self.assertEqual(second.summary, "fixed the steps")
        self.assertEqual(second.author, self.agent)
        self.assertEqual([v.number for v in page.versions.all()], [2, 1])


class PageTemplateTest(TestCase):
    def test_builtin_templates_exist(self):
        templates = {t.name: t for t in PageTemplate.objects.filter(is_builtin=True)}
        self.assertLessEqual({"Runbook", "Post-mortem", "How-to"}, set(templates))

        runbook = templates["Runbook"].body
        for heading in ["## Purpose", "## Before you start", "## Steps", "## Rollback"]:
            self.assertIn(heading, runbook)

        post_mortem = templates["Post-mortem"].body
        for heading in [
            "## Summary",
            "## Impact",
            "## Timeline",
            "## Root cause",
            "## What went well",
            "## What to change",
        ]:
            self.assertIn(heading, post_mortem)
        self.assertIn("- [ ]", post_mortem)

        how_to = templates["How-to"].body
        for heading in ["## Goal", "## Steps", "## Troubleshooting"]:
            self.assertIn(heading, how_to)


class PageLinkTypeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.space = Space.objects.create(name="Ops")
        cls.internal = Page.objects.create(space=cls.space, title="Internal runbook")
        cls.published = Page.objects.create(
            space=cls.space, title="Reset your password", is_published_to_help_center=True
        )
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.customer = User.objects.create_user("cust1", password="x", role="customer")

    def test_page_link_type_is_registered(self):
        self.assertIn("page", types())
        self.assertEqual(
            get_resolver("page").search("runbook", self.agent, 5)[0].id, str(self.internal.pk)
        )

    def test_staff_resolve_every_page_and_customers_only_published_ones(self):
        wanted = [str(self.internal.pk), str(self.published.pk)]
        agent_ids = set(get_resolver("page").resolve(wanted, self.agent))
        customer_ids = set(get_resolver("page").resolve(wanted, self.customer))
        self.assertEqual(agent_ids, set(wanted))
        self.assertEqual(customer_ids, {str(self.published.pk)})

    def test_from_url_matches_the_pages_own_address(self):
        url = f"http://localhost{self.published.get_absolute_url()}"
        self.assertEqual(get_resolver("page").from_url(url), str(self.published.pk))
        self.assertIsNone(get_resolver("page").from_url("/wiki/p/not-a-page/"))

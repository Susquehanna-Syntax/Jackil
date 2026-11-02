"""Moving the Knowledge Base into the wiki, one migration function at a time.

The migration runs inside ``migrate``, where the app registry holds historical
models. Tests call it with ``django.apps.apps`` — the live registry — after
putting KB rows on the table: the same code path against the final model state.

The test database has run both ``kb.0002_seed_kb`` and this migration, so the
demo articles are already pages by the time a case starts. Each one empties the
KB tables and drops the imported space — ``TestCase`` rolls that back, so other
suites still find the demo rows and their ids when they come — then imports what
the case itself created.
"""

import sys
from datetime import timedelta

from django.apps import apps as global_apps
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.kb.models import KBArticle, KBCategory
from apps.wiki.models import Page, PageVersion, Space

DRAFT_PREFIX = "Draft from the Knowledge Base. "


def load_migration():
    """The migration module: its name starts with a digit, so no import statement."""
    from django.db.migrations.loader import MigrationLoader

    # ``Migration.__module__`` is the dotted name of the file it lives in; the
    # loader has already put that module into ``sys.modules``.
    migration = MigrationLoader(connection).get_migration("wiki", "0003_import_kb")
    return sys.modules[migration.__module__]


def run():
    load_migration().import_kb(global_apps, None)


class ImportTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("writer", password="x", role="agent")

    # ``TestCase`` writes are rolled back, so dropping what the migrations left
    # behind is safe: the space's id continues from here, and no article in any
    # test wants a slug one of the demo pages already holds.
    def setUp(self):
        KBArticle.objects.all().delete()
        KBCategory.objects.all().delete()
        Space.objects.filter(slug="help-center").delete()

    def category(self, name, **kwargs):
        return KBCategory.objects.create(name=name, order=kwargs.pop("order", 0), **kwargs)

    def article(self, title, slug="", **kwargs):
        kwargs.setdefault("body", f"{title} body")
        return KBArticle.objects.create(
            title=title, slug=slug or slugify(title)[:220], author=self.author, **kwargs
        )

    def pages(self):
        return {
            page.slug: Page.objects.get(pk=page.pk) if False else page
            for page in Space.objects.get(slug="help-center").pages.all()
        }

    def test_every_category_and_article_arrives(self):
        getting_started = self.category("Getting Started", order=1)
        self.category("Billing", description="Invoices and plans.", order=2)
        self.article("Set up your account", category=getting_started)
        run()
        pages = self.pages()
        self.assertEqual(
            {page.title for page in pages.values()},
            {"Getting Started", "Billing", "Set up your account"},
        )
        billing = pages["billing"]
        self.assertEqual(billing.body, "Invoices and plans.")
        self.assertEqual(billing.summary, "Invoices and plans.")
        self.assertFalse(billing.is_published_to_help_center)

    def test_the_space_is_the_help_center_one(self):
        run()
        space = Space.objects.get(slug="help-center")
        self.assertEqual(space.name, "Help Center")
        self.assertEqual(space.icon_color, "lavender")
        self.assertEqual(space.description, "Articles moved from the Knowledge Base.")

    def test_article_slug_is_kept_and_a_clashing_category_slug_moves(self):
        clash = self.category("Reset Password", order=1)
        article = self.article("Reset Password", category=clash)
        run()
        pages = self.pages()
        article.refresh_from_db()
        self.assertEqual(article.slug, "reset-password")
        self.assertEqual(pages["reset-password"].parent_id, pages["reset-password-2"].pk)
        self.assertEqual(pages["reset-password"].title, article.title)
        self.assertEqual(pages["reset-password-2"].title, clash.name)

    def test_uncategorised_article_is_top_level(self):
        orphan = self.article("Loose Ends")
        run()
        orphan.refresh_from_db()
        page = Page.objects.get(slug=orphan.slug)
        self.assertIsNone(page.parent)
        self.assertEqual(page.space.slug, "help-center")

    def test_empty_body_is_fine(self):
        empty = self.article("Nothing Here", body="", summary="")
        run()
        empty.refresh_from_db()
        page = Page.objects.get(slug=empty.slug)
        self.assertEqual(page.body, "")
        self.assertEqual(page.summary, "")

    def test_public_flag_maps_to_help_center(self):
        cat = self.category("Guides", order=1)
        shown = self.article("Public one", category=cat, is_published=True, is_public=True)
        hidden = self.article("Internal one", category=cat, is_published=True, is_public=False)
        draft = self.article("Draft one", category=cat, is_published=False)
        run()
        shown.refresh_from_db()
        hidden.refresh_from_db()
        draft.refresh_from_db()
        self.assertTrue(Page.objects.get(slug=shown.slug).is_published_to_help_center)
        self.assertFalse(Page.objects.get(slug=hidden.slug).is_published_to_help_center)
        self.assertFalse(Page.objects.get(slug=draft.slug).is_published_to_help_center)
        # A category reaches the help center only through a published public article.
        self.assertTrue(Page.objects.get(slug="guides").is_published_to_help_center)

    def test_a_category_without_public_articles_stays_internal(self):
        self.category("Notes", order=1)
        self.article("Internal only", is_published=True, is_public=False)
        run()
        self.assertFalse(self.pages()["notes"].is_published_to_help_center)

    def test_draft_article_is_internal_and_marked(self):
        draft = self.article("Work in progress", summary="Half written.", is_published=False)
        run()
        draft.refresh_from_db()
        page = Page.objects.get(slug=draft.slug)
        self.assertFalse(page.is_published_to_help_center)
        self.assertEqual(page.summary, f"{DRAFT_PREFIX}Half written.")

    def test_views_dates_and_author_are_kept(self):
        old = timezone.now() - timedelta(days=30)
        edited = timezone.now() - timedelta(days=3)
        article = self.article("Kept Whole", views=42)
        KBArticle.objects.filter(pk=article.pk).update(created_at=old, updated_at=edited)
        run()
        article.refresh_from_db()
        page = Page.objects.get(slug=article.slug)
        self.assertEqual(page.views, 42)
        self.assertEqual(page.author_id, self.author.pk)
        self.assertEqual(page.created_at, article.created_at)
        self.assertEqual(page.updated_at, article.updated_at)

    def test_import_is_idempotent(self):
        cat = self.category("Guides", order=1)
        self.article("Set up your account", category=cat)
        run()
        first = sorted(Page.objects.values_list("slug", flat=True))
        versions = PageVersion.objects.count()
        run()
        self.assertEqual(sorted(Page.objects.values_list("slug", flat=True)), first)
        self.assertEqual(PageVersion.objects.count(), versions)

    def test_each_page_has_version_1(self):
        cat = self.category("Guides", order=1)
        self.article("Set up your account", category=cat)
        run()
        for page in Space.objects.get(slug="help-center").pages.all():
            version = page.versions.get(number=1)
            self.assertEqual(version.title, page.title)
            self.assertEqual(version.body, page.body)
            self.assertEqual(version.summary, "Imported from the Knowledge Base")

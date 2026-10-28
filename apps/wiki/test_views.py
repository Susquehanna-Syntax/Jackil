"""The staff wiki screens: permissions, saving, versions, diff, restore."""

import hashlib
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.wiki.models import Page, PageTemplate, Space
from apps.wiki.service import save_version


class WikiAccessTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.admin = User.objects.create_user("admin1", password="x", role="admin")
        cls.customer = User.objects.create_user("cust1", password="x", role="customer")
        cls.space = Space.objects.create(name="Ops")
        cls.other_space = Space.objects.create(name="Other")
        cls.page = Page.objects.create(space=cls.space, title="Reset a password", body="v1")

    def wiki_urls(self):
        p = self.page.slug
        s = self.space.slug
        return [
            ("get", reverse("wiki:home")),
            ("get", reverse("wiki:space_detail", args=[s])),
            ("get", reverse("wiki:page_detail", args=[p])),
            ("get", reverse("wiki:page_edit", args=[p])),
            ("get", reverse("wiki:page_new")),
            ("get", reverse("wiki:page_history", args=[p])),
            ("get", reverse("wiki:page_version", args=[p, 1])),
            ("get", reverse("wiki:page_diff", args=[p])),
            ("post", reverse("wiki:page_restore", args=[p, 1])),
            ("post", reverse("wiki:page_move", args=[p])),
            ("get", reverse("wiki:page_delete", args=[p])),
            ("get", reverse("wiki:space_create")),
            ("get", reverse("wiki:space_edit", args=[s])),
        ]

    def test_customer_gets_403_from_every_wiki_view(self):
        self.client.force_login(self.customer)
        for method, url in self.wiki_urls():
            with self.subTest(url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 403)

    def test_anonymous_is_sent_to_sign_in(self):
        response = self.client.get(reverse("wiki:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_sidebar_has_wiki_for_staff_only(self):
        self.client.force_login(self.agent)
        body = self.client.get(reverse("wiki:home")).content.decode()
        self.assertIn('data-tip="Wiki"', body)
        self.assertIn("/wiki/", body)

        self.client.force_login(self.customer)
        body = self.client.get(reverse("help:home")).content.decode()
        self.assertNotIn('data-tip="Wiki"', body)


class PageSaveTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.admin = User.objects.create_user("admin1", password="x", role="admin")
        cls.space = Space.objects.create(name="Ops")
        cls.other_space = Space.objects.create(name="Other")

    def post_page(self, *, title="Runbook", body="steps", space="ops", parent="", summary=""):
        return self.client.post(
            reverse("wiki:page_new"),
            {"title": title, "body": body, "space": space, "parent": parent, "summary": summary},
        )

    def test_agent_creates_a_page_and_version_1_is_recorded(self):
        self.client.force_login(self.agent)
        response = self.post_page(title="Rotate the keys", body="rotate nightly", summary="created")

        page = Page.objects.get(slug="rotate-the-keys")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, page.get_absolute_url())
        self.assertEqual(page.space, self.space)
        self.assertEqual(page.author, self.agent)
        self.assertEqual(page.updated_by, self.agent)

        version = page.versions.get()
        self.assertEqual(version.number, 1)
        self.assertEqual(version.body, "rotate nightly")
        self.assertEqual(version.summary, "created")
        self.assertEqual(version.author, self.agent)

    def test_edit_records_a_new_version_with_summary(self):
        page = Page.objects.create(space=self.space, title="Runbook", body="v1", author=self.agent)
        save_version(page, self.agent, summary="created")
        self.client.force_login(self.agent)
        response = self.client.post(
            reverse("wiki:page_edit", args=[page.slug]),
            {"title": "Runbook", "body": "v2", "space": self.space.slug, "summary": "fixed steps"},
        )

        self.assertEqual(response.status_code, 302)
        page.refresh_from_db()
        self.assertEqual(page.body, "v2")
        # The page's own body was already version 1; the edit is version 2.
        self.assertEqual([v.number for v in page.versions.all()], [2, 1])
        self.assertEqual(page.versions.get(number=1).body, "v1")
        self.assertEqual(page.versions.get(number=2).summary, "fixed steps")

    def test_a_blank_title_is_refused_and_nothing_is_saved(self):
        self.client.force_login(self.agent)
        response = self.post_page(title="   ")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A page needs a title.", status_code=200)
        self.assertFalse(Page.objects.filter(space=self.space).exists())

    def test_an_overlong_body_is_refused(self):
        before = Page.objects.count()  # the KB import migration seeds pages
        self.client.force_login(self.agent)
        response = self.post_page(body="x" * 1_000_001)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1,000,000", status_code=200)
        self.assertEqual(Page.objects.count(), before)

    def test_new_page_from_template_starts_with_its_body(self):
        template = PageTemplate.objects.get(name="Runbook")
        self.client.force_login(self.agent)
        response = self.client.get(f"{reverse('wiki:page_new')}?template={template.pk}")

        self.assertContains(response, "## Rollback")
        textarea = response.content.decode().split('<textarea class="form-input wiki-editor"')[1]
        self.assertIn("## Rollback", textarea.split("</textarea>")[0])

    def test_saving_a_template_body_creates_the_page_with_it(self):
        template = PageTemplate.objects.get(name="How-to")
        self.client.force_login(self.agent)
        self.post_page(title="Wire a desk", body=template.body)

        self.assertEqual(Page.objects.get(slug="wire-a-desk").body, template.body)

    def test_parent_in_another_space_is_refused(self):
        foreign = Page.objects.create(space=self.other_space, title="Foreign root")
        self.client.force_login(self.agent)
        response = self.post_page(title="Child", parent=foreign.slug)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "same space", status_code=200)
        self.assertFalse(Page.objects.filter(title="Child").exists())

    def test_only_admin_deletes_pages_and_children_go_too(self):
        root = Page.objects.create(space=self.space, title="Root")
        child = Page.objects.create(space=self.space, title="Child", parent=root)

        self.client.force_login(self.agent)
        self.assertEqual(
            self.client.get(reverse("wiki:page_delete", args=[root.slug])).status_code, 403
        )
        self.assertEqual(
            self.client.post(reverse("wiki:page_delete", args=[root.slug])).status_code, 403
        )
        self.assertTrue(Page.objects.filter(pk=root.pk).exists())

        self.client.force_login(self.agent)
        self.assertNotContains(self.client.get(root.get_absolute_url()), "Delete", status_code=200)

        self.client.force_login(self.admin)
        confirm = self.client.get(reverse("wiki:page_delete", args=[root.slug]))
        self.assertContains(confirm, "child page", status_code=200)

        response = self.client.post(reverse("wiki:page_delete", args=[root.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Page.objects.filter(pk__in=[root.pk, child.pk]).exists())


class PageMoveTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.space = Space.objects.create(name="Ops")
        cls.other_space = Space.objects.create(name="Other")

    def test_move_into_own_descendant_is_refused(self):
        root = Page.objects.create(space=self.space, title="Root")
        middle = Page.objects.create(space=self.space, title="Middle", parent=root)
        leaf = Page.objects.create(space=self.space, title="Leaf", parent=middle)

        self.client.force_login(self.agent)
        response = self.client.post(
            reverse("wiki:page_move", args=[root.slug]), {"parent": leaf.slug}
        )

        self.assertEqual(response.status_code, 302)
        root.refresh_from_db()
        self.assertIsNone(root.parent_id)

        follow = self.client.get(root.get_absolute_url())
        self.assertContains(follow, "descendant", status_code=200)

    def test_move_to_a_parent_in_another_space_is_refused(self):
        page = Page.objects.create(space=self.space, title="Page")
        foreign = Page.objects.create(space=self.other_space, title="Foreign")

        self.client.force_login(self.agent)
        self.client.post(reverse("wiki:page_move", args=[page.slug]), {"parent": foreign.slug})

        page.refresh_from_db()
        self.assertIsNone(page.parent_id)

    def test_move_within_the_space_reparents_and_sets_order(self):
        root = Page.objects.create(space=self.space, title="Root")
        page = Page.objects.create(space=self.space, title="Page")

        self.client.force_login(self.agent)
        self.client.post(
            reverse("wiki:page_move", args=[page.slug]), {"parent": root.slug, "order": "3"}
        )

        page.refresh_from_db()
        self.assertEqual(page.parent_id, root.pk)
        self.assertEqual(page.order, 3)


class VersionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.space = Space.objects.create(name="Ops")

    def make_versions(self):
        """A page saved three times, each save snapshotted: versions 1..3."""
        page = Page.objects.create(space=self.space, title="Runbook", body="line one")
        for body, summary in [
            ("line one", "created"),
            ("line one\nline two", "second"),
            ("line one\nline two\nline three", "third"),
        ]:
            page.body = body
            page.save()
            save_version(page, self.agent, summary=summary)
        return page

    def test_history_lists_versions_newest_first(self):
        page = self.make_versions()
        self.client.force_login(self.agent)
        response = self.client.get(reverse("wiki:page_history", args=[page.slug]))

        content = response.content.decode()
        self.assertLess(content.index(">Version 3</a>"), content.index(">Version 2</a>"))
        self.assertLess(content.index("Version 2</a>"), content.index(">Version 1</a>"))

    def test_diff_shows_added_and_removed_lines(self):
        page = self.make_versions()
        self.client.force_login(self.agent)
        response = self.client.get(f"{reverse('wiki:page_diff', args=[page.slug])}?a=1&b=3")

        content = response.content.decode()
        self.assertIn('<span class="add">+line three</span>', content)
        self.assertIn("<pre", content)

    def test_diff_of_a_removed_line(self):
        page = self.make_versions()
        self.client.force_login(self.agent)
        response = self.client.get(f"{reverse('wiki:page_diff', args=[page.slug])}?a=3&b=1")

        self.assertContains(response, '<span class="del">-line three</span>', status_code=200)

    def test_diff_escapes_the_line(self):
        page = self.make_versions()
        later = page.versions.get(number=2)
        later.body = "<script>alert(1)</script>"
        later.save()

        self.client.force_login(self.agent)
        response = self.client.get(f"{reverse('wiki:page_diff', args=[page.slug])}?a=1&b=2")

        content = response.content.decode()
        self.assertIn("&lt;script&gt;", content)
        self.assertNotIn('<span class="add"><script>', content)

    def test_missing_versions_are_404(self):
        page = self.make_versions()
        self.client.force_login(self.agent)
        diff = reverse("wiki:page_diff", args=[page.slug])
        self.assertEqual(self.client.get(f"{diff}?a=99&b=3").status_code, 404)
        self.assertEqual(self.client.get(f"{diff}?a=1&b=99").status_code, 404)

    def test_diff_defaults_to_previous_against_current(self):
        page = self.make_versions()
        self.client.force_login(self.agent)
        response = self.client.get(reverse("wiki:page_diff", args=[page.slug]))

        self.assertContains(response, "Version 2 &rarr; version 3")
        self.assertContains(response, '<span class="add">+line three</span>', status_code=200)

    def test_restore_creates_a_new_version(self):
        page = self.make_versions()
        self.client.force_login(self.agent)
        response = self.client.post(reverse("wiki:page_restore", args=[page.slug, 1]), follow=True)

        page.refresh_from_db()
        self.assertEqual(page.body, "line one")
        self.assertEqual(page.updated_by, self.agent)
        latest = page.versions.order_by("-number").first()
        self.assertEqual(latest.number, 4)
        self.assertEqual(latest.summary, "Restored version 1")
        self.assertEqual(latest.body, "line one")
        self.assertContains(response, "Version 1 restored.")


class PageViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.space = Space.objects.create(name="Ops")
        cls.page = Page.objects.create(
            space=cls.space,
            title="Rotations",
            body="Cost $a^2$ inline.\n\n$$\\int_0^1 x\\,dx$$\n",
        )

    def test_page_detail_loads_katex_and_renders_math_markup(self):
        self.client.force_login(self.agent)
        response = self.client.get(self.page.get_absolute_url())

        self.assertContains(response, "css/vendor/katex/katex.min.css")
        self.assertContains(response, "js/vendor/katex/katex.min.js")
        self.assertContains(response, "js/jackil-math.js")
        self.assertContains(response, '<article class="markdown-body" data-markdown>')
        self.assertIn('<span class="math inline">a^2</span>', response.content.decode())

    def test_breadcrumbs_children_and_history_link(self):
        child = Page.objects.create(space=self.space, title="Nightly", parent=self.page)
        self.client.force_login(self.agent)
        response = self.client.get(self.page.get_absolute_url())

        self.assertContains(response, "Ops")
        self.assertContains(response, child.get_absolute_url())
        self.assertContains(response, reverse("wiki:page_history", args=[self.page.slug]))
        self.assertContains(response, "Linked from")

    def test_view_count_increments(self):
        self.client.force_login(self.agent)
        self.client.get(self.page.get_absolute_url())
        self.client.get(self.page.get_absolute_url())

        self.page.refresh_from_db()
        self.assertEqual(self.page.views, 2)

    def test_the_tree_marks_the_current_page(self):
        self.client.force_login(self.agent)
        response = self.client.get(self.page.get_absolute_url())

        self.assertContains(response, 'class="current"')


class EditorPreviewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.space = Space.objects.create(name="Ops")

    def test_the_preview_holds_the_saved_body_and_the_form_has_the_editor_classes(self):
        page = Page.objects.create(space=self.space, title="Saved", body="**kept**")
        self.client.force_login(self.agent)
        response = self.client.get(reverse("wiki:page_edit", args=[page.slug]))

        preview = response.content.decode().split('class="wiki-preview markdown-body"')[1]
        self.assertIn("<strong>kept</strong>", preview.split("</div>")[0])
        self.assertContains(response, '<textarea class="form-input wiki-editor" name="body"')

    def test_a_new_pages_preview_is_empty(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("wiki:page_new"))

        preview = response.content.decode().split('class="wiki-preview markdown-body"')[1]
        self.assertNotIn("<p><strong>", preview.split("</div>")[0])


class KaTeXVendorTest(TestCase):
    def test_katex_is_the_pinned_build(self):
        path = Path(settings.BASE_DIR) / "static/js/vendor/katex/katex.min.js"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(digest, "103a53763cc033bba8d175bf3f0ba597c3505c9b6747dd3f2c7bc2a6bfcc8ae7")

    def test_the_css_and_its_fonts_came_across_together(self):
        root = Path(settings.BASE_DIR) / "static/css/vendor/katex"
        self.assertEqual(
            hashlib.sha256((root / "katex.min.css").read_bytes()).hexdigest(),
            "d4ab5b8ee16989b070cdb0ea24bd6ad48fc8df1b787f280f29d3ae4f959f2c00",
        )
        self.assertEqual(len(list((root / "fonts").glob("*.woff2"))), 20)

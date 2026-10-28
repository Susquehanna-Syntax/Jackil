import time

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.tickets.models import Ticket
from apps.wiki.markdown import MAX_SOURCE, render
from apps.wiki.models import Page, Space


def _assert_no_live_markup(html):
    """Nothing a writer typed survives as live markup or as an executable URL."""
    lowered = html.lower()
    for fragment in ("<script", "<img", "<iframe", "<svg"):
        assert fragment not in lowered, f"{fragment!r} found in {html!r}"
    assert "javascript:" not in lowered, html


class RendererTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.customer = User.objects.create_user("cust1", password="x", role="customer")
        cls.space = Space.objects.create(name="Ops")

    def render(self, md, user=None, links=True):
        return str(render(md, user=self.agent if user is None else user, links=links))

    def ticket_chip(self, title="VPN is down", customer=None):
        return Ticket.objects.create(
            title=title, created_by=self.customer if customer is None else customer
        )

    def test_math_inline_and_block_are_marked_for_katex(self):
        html = self.render("$a^2$\n\n$$\\int x$$")
        self.assertIn('<span class="math inline">a^2</span>', html)
        self.assertIn('<div class="math block">', html)
        self.assertIn("\\int x", html)

    def test_callouts_note_warning_danger(self):
        html = self.render(
            "> [!NOTE]\n> Useful\n\n> [!WARNING]\n> Careful\n\n> [!CAUTION]\n> Risky"
        )
        self.assertIn("markdown-alert-note", html)
        self.assertIn('<p class="markdown-alert-title">Note</p>', html)
        self.assertIn("markdown-alert-warning", html)
        self.assertIn('<p class="markdown-alert-title">Warning</p>', html)
        # GitHub's CAUTION alert is the library's danger-tinted callout.
        self.assertIn("markdown-alert-caution", html)
        self.assertIn('<p class="markdown-alert-title">Caution</p>', html)
        self.assertIn("<p>Careful</p>", html)

    def test_code_is_highlighted(self):
        html = self.render("```python\nprint(1)\n```")
        self.assertIn('<pre><code class="language-python">', html)
        self.assertIn('<span class="nb">print</span>', html)

    def test_unknown_lexer_falls_back_to_plain_code(self):
        html = self.render("```not-a-language\nstuff & <b>\n```")
        self.assertIn("<pre><code", html)
        self.assertIn("stuff &amp; &lt;b&gt;", html)

    def test_tables_and_task_lists(self):
        html = self.render("| A | B |\n|---|--:|\n| 1 | 2 |\n\n- [x] done\n- [ ] todo")
        self.assertIn("<table>", html)
        self.assertIn('style="text-align:right"', html)
        self.assertIn('type="checkbox"', html)
        self.assertIn("checked", html)

    def test_wikilink_to_existing_page_links_to_it(self):
        page = Page.objects.create(space=self.space, title="Onboarding")
        html = self.render("See [[Onboarding]].")
        self.assertIn(f'href="{page.get_absolute_url()}"', html)
        self.assertIn(">Onboarding</a>", html)
        self.assertNotIn("broken", html)

    def test_wikilink_alias_is_plain_text_for_everyone_but_its_writer(self):
        page = Page.objects.create(space=self.space, title="Onboarding")
        # Once the placeholder passes the sanitiser its target is gone and only
        # the alias is left, which is no proof of what the link was aimed at.
        # Phase 02's editor renders with links=False and draws its own resolved
        # chip from the source text; see apps/wiki/markdown.py's module docstring.
        html = self.render(f"[[{page.title}|the onboarding guide]]")
        self.assertEqual("<p>the onboarding guide</p>\n", html)

    def test_wikilink_matching_a_page_title_links_to_it(self):
        page = Page.objects.create(space=self.space, title="Onboarding")
        html = self.render("[[Onboarding]]")
        self.assertIn(f'href="{page.get_absolute_url()}"', html)

    def test_wikilink_to_missing_page_is_marked_broken_with_new_page_url(self):
        html = self.render("See [[Ghost Page]].")
        self.assertIn('class="wikilink broken"', html)
        self.assertIn(f'href="{reverse("wiki:page_new")}?title=Ghost%20Page"', html)
        self.assertIn('title="No page called Ghost Page yet"', html)

    def test_dynamic_link_chip_for_a_ticket(self):
        ticket = self.ticket_chip()
        html = self.render(f"[[ticket:{ticket.pk}]]")
        self.assertIn("VPN is down", html)
        self.assertIn(reverse("tickets:ticket_detail", args=[ticket.pk]), html)
        self.assertIn(ticket.get_status_display(), html)
        self.assertIn("<small>", html)

    def test_dynamic_link_chip_hidden_from_a_customer(self):
        ticket = self.ticket_chip()
        html = self.render(f"[[ticket:{ticket.pk}]]", user=self.customer)
        self.assertNotIn("VPN is down", html)
        self.assertNotIn("hidden-target", html)
        self.assertNotIn("<a", html)

    def test_vigil_chip_shows_unavailable(self):
        html = self.render("[[vigil:host:mx-01]]")
        self.assertIn("unavailable", html)
        self.assertIn("mx-01", html)

    def test_an_unresolvable_chip_keeps_the_text_it_was_given(self):
        html = self.render("[[ticket:4321|gone away]]")
        self.assertEqual("<p>gone away</p>\n", html)

    def _assert_inert(self, html):
        _assert_no_live_markup(html)

    def test_script_tag_is_neutralised(self):
        html = self.render("<script>alert(1)</script>")
        self._assert_inert(html)
        self.assertIn("&lt;script&gt;", html)

    def test_javascript_link_is_neutralised(self):
        html = self.render("[click](javascript:alert(1))")
        self.assertNotIn('href="javascript', html)
        self.assertNotIn("<a ", html)

    def test_img_onerror_is_neutralised(self):
        html = self.render("<img src=x onerror=alert(1)>")
        self._assert_inert(html)
        self.assertNotIn("<img", html)

    def test_wikilink_text_is_escaped(self):
        html = self.render("[[<img src=x onerror=alert(1)>]]")
        self._assert_inert(html)
        self.assertIn("&lt;img", html)

    def test_chip_label_is_escaped(self):
        ticket = self.ticket_chip("<script>alert(1)</script>")
        html = self.render(f"[[ticket:{ticket.pk}]]")
        self._assert_inert(html)
        self.assertIn("&lt;script&gt;", html)

    def test_unbalanced_math_renders_as_text(self):
        html = self.render("$$ x")
        self.assertIn("x", html)
        self.assertNotIn("math block", html)

    def test_very_long_page_is_truncated_with_a_note(self):
        start = time.monotonic()
        html = self.render("# Heading\n\n" + "a" * 1_000_000)
        self.assertLess(time.monotonic() - start, 5.0)
        self.assertTrue(html.startswith('<div class="markdown-alert markdown-alert-note">'))
        self.assertIn("only the first part is shown", html)
        self.assertLessEqual(len(html), MAX_SOURCE + 400)

    def test_links_false_resolves_nothing_and_shows_no_targets(self):
        Page.objects.create(space=self.space, title="Onboarding")
        html = self.render("See [[Onboarding]]. and [[ticket:1]]", links=False)
        self.assertIn("<p>See Onboarding. and ticket:1</p>\n", html)

    def test_no_reader_renders_no_links_at_all(self):
        Page.objects.create(space=self.space, title="Onboarding")
        html = str(render("See [[Onboarding]]. and [[ticket:1]]", user=None))
        self.assertIn("<p>See Onboarding. and ticket:1</p>\n", html)
        self.assertNotIn("<a", html)
        self.assertNotIn("href=", html)
        self.assertNotIn("data-dl-held", html)

    def test_empty_body_renders_empty(self):
        self.assertEqual(self.render(""), "")


class ReaderScopedPageLinkTests(TestCase):
    """A customer's render must not reveal internal pages or offer to create one."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("scope-agent", "sa@x.com", "pw", role="agent")
        cls.customer = User.objects.create_user("scope-cust", "sc@x.com", "pw", role="customer")
        space = Space.objects.create(name="Scope")
        # Titles no migration seeds, so lookups find exactly these pages.
        cls.internal = Page.objects.create(space=space, title="Scope firewall rules")
        cls.public = Page.objects.create(
            space=space, title="Scope published guide", is_published_to_help_center=True
        )

    def test_customer_does_not_get_a_link_to_an_internal_page(self):
        html = str(render("See [[Scope firewall rules]].", user=self.customer))
        self.assertNotIn(self.internal.slug, html)
        self.assertNotIn("<a", html)
        self.assertIn("Scope firewall rules", html)

    def test_customer_is_not_offered_a_new_page(self):
        html = str(render("See [[No such page]].", user=self.customer))
        self.assertNotIn(reverse("wiki:page_new"), html)
        self.assertNotIn("<a", html)

    def test_customer_still_gets_links_to_published_pages(self):
        html = str(render("See [[Scope published guide]].", user=self.customer))
        # A customer cannot open /wiki/; their links go to the help center.
        self.assertIn(reverse("help:article", args=[self.public.slug]), html)
        self.assertNotIn("/wiki/", html)

    def test_staff_link_to_internal_pages_and_are_offered_new_ones(self):
        html = str(render("[[Scope firewall rules]] and [[No such page]]", user=self.agent))
        self.assertIn(self.internal.slug, html)
        self.assertIn(reverse("wiki:page_new"), html)

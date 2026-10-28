"""What a page body points at, and what a save turns those references into."""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.links.models import DynamicLink
from apps.links.service import add_link
from apps.tickets.models import Ticket
from apps.wiki.models import Page, Space
from apps.wiki.references import extract_links, extract_references, extract_titles
from apps.wiki.service import backlinks_for, save_page_links


class ExtractReferencesTest(TestCase):
    def test_extracts_pages_and_dynamic_links(self):
        body = (
            "See [[Reset your password]] and the aliased [[Runbook|the steps]].\n\n"
            "Chips: [[ticket:1423]], [[item:Mail server]], [[vigil:host:mx-01]].\n"
        )

        titles, links = extract_references(body)

        self.assertEqual(titles, {"Reset your password", "Runbook"})
        self.assertEqual(
            links,
            {("ticket", "1423"), ("item", "Mail server"), ("vigil:host", "mx-01")},
        )
        # Both halves are importable on their own, and agree with the pair.
        self.assertEqual(extract_titles(body), titles)
        self.assertEqual(extract_links(body), links)

    def test_ignores_references_in_code(self):
        body = (
            "Use [[Runbook]] in prose.\n\n"
            "```markdown\n"
            "A fence documents: [[ticket:99]] and [[Runbook in a fence]]\n"
            "```\n\n"
            "An inline `[[item:Secrets]]` span is code too.\n"
        )

        titles, links = extract_references(body)

        self.assertEqual(titles, {"Runbook"})
        self.assertEqual(links, set())

    def test_a_wordy_wikilink_is_not_a_dynamic_link(self):
        titles, links = extract_references("A [[Page: with a colon]] title stays a page.")

        self.assertEqual(titles, {"Page: with a colon"})
        self.assertEqual(links, set())


class BacklinksTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.space = Space.objects.create(name="Ops")
        cls.mail = Page.objects.create(space=cls.space, title="Mail server")
        cls.backup = Page.objects.create(space=cls.space, title="Nightly backup")
        cls.alias = Page.objects.create(space=cls.space, title="Aliases", body="nothing yet")
        cls.unrelated = Page.objects.create(space=cls.space, title="Printers")

    def test_backlinks_match_whole_titles_only(self):
        # "Mail server backup" is a page whose *body* links to the longer title:
        # it contains "[[Mail server" and is not a link to "Mail server".
        Page.objects.filter(title="Nightly backup").update(
            body="Backups cover [[Mail server backup]] only."
        )
        Page.objects.filter(title="Aliases").update(body="Same box, fewer words: [[MAIL SERVER]].")

        titles = [page.title for page in backlinks_for(self.mail)]

        self.assertEqual(titles, ["Aliases"])

    def test_an_aliased_wikilink_counts_and_a_page_is_never_its_own_backlink(self):
        Page.objects.filter(title="Nightly backup").update(body="See [[Mail server|the box]].")
        Page.objects.filter(title="Mail server").update(body="Self note: [[Mail server]].")

        titles = [page.title for page in backlinks_for(self.mail)]

        self.assertEqual(titles, ["Nightly backup"])

    def test_a_page_with_nothing_pointing_at_it_has_no_backlinks(self):
        self.assertEqual(backlinks_for(self.unrelated), [])


class ChipLinksOnSaveTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.customer = User.objects.create_user("cust1", password="x", role="customer")
        cls.space = Space.objects.create(name="Ops")
        cls.mine = Ticket.objects.create(
            title="Mailbox full", description="it is full", created_by=cls.agent
        )
        cls.theirs = Ticket.objects.create(
            title="Someone else's mailbox", description="private", created_by=cls.customer
        )

    def save_page(self, body, *, slug="mail-notes", title="Mail notes"):
        self.client.force_login(self.agent)
        self.client.post(
            reverse("wiki:page_new"),
            {"title": title, "body": body, "space": self.space.slug, "parent": ""},
        )
        return Page.objects.get(slug=slug)

    def edit_page(self, page, body):
        self.client.force_login(self.agent)
        return self.client.post(
            reverse("wiki:page_edit", args=[page.slug]),
            {"title": page.title, "body": body, "space": page.space.slug, "parent": ""},
        )

    def links_of(self, page):
        return {
            (link.target_type, link.target_id)
            for link in DynamicLink.objects.filter(source_type="page", source_id=str(page.pk))
        }

    def test_saving_a_page_with_a_chip_creates_a_relates_to_link(self):
        page = self.save_page(f"Escalated from [[ticket:{self.mine.pk}]]; see [[Onboarding]].")

        self.assertEqual(self.links_of(page), {("ticket", str(self.mine.pk))})
        link = DynamicLink.objects.get(source_type="page", source_id=str(page.pk))
        self.assertEqual(link.relation, "relates_to")
        self.assertEqual(link.created_by_id, self.agent.pk)

        # Saving the same page again adds nothing: an existing link is ordinary.
        self.edit_page(page, page.body)
        self.assertEqual(self.links_of(page), {("ticket", str(self.mine.pk))})
        self.assertEqual(DynamicLink.objects.count(), 1)

    def test_a_wikilink_to_another_page_links_the_two(self):
        target = Page.objects.create(space=self.space, title="Onboarding", body="welcome")

        page = self.save_page("Start with [[onboarding|the first day]].")

        self.assertEqual(self.links_of(page), {("page", str(target.pk))})

    def test_chip_to_a_hidden_target_is_ignored_on_save(self):
        # The ticket is someone else's, and this account cannot see it. What the
        # page says about it is prose, not a link anyone may follow. (An agent
        # sees every ticket in this app, so the visibility rule is what stands in
        # for an account that genuinely could not.)
        with patch("apps.links.builtin._visible", return_value=False):
            page = self.save_page(f"Looks like [[ticket:{self.theirs.pk}]].")

        self.assertEqual(self.links_of(page), set())
        # …and the page is saved anyway, chip and all.
        self.assertEqual(page.body, f"Looks like [[ticket:{self.theirs.pk}]].")

    def test_removing_a_chip_keeps_the_link(self):
        page = self.save_page(f"Escalated from [[ticket:{self.mine.pk}]].")
        self.assertEqual(self.links_of(page), {("ticket", str(self.mine.pk))})

        self.edit_page(page, "the chip is gone from the text")

        # Someone may have added that link by hand; an edit does not undo it.
        self.assertEqual(self.links_of(page), {("ticket", str(self.mine.pk))})

    def test_a_link_to_the_page_itself_is_never_created(self):
        ticket = Ticket.objects.create(
            title="Printer offline", description="gone", created_by=self.agent
        )
        page = Page.objects.create(
            space=self.space, title="Mail notes", body=f"[[ticket:{ticket.pk}]]"
        )
        save_page_links(page, self.agent)

        Page.objects.filter(pk=page.pk).update(
            body=f"As [[Mail notes]] says, [[ticket:{ticket.pk}]]."
        )
        page.refresh_from_db()
        save_page_links(page, self.agent)

        self.assertEqual(self.links_of(page), {("ticket", str(ticket.pk))})
        self.assertEqual(DynamicLink.objects.count(), 1)

    def test_a_link_of_another_relation_does_not_block_the_relates_to_one(self):
        ticket = Ticket.objects.create(
            title="Printer offline", description="gone", created_by=self.agent
        )
        page = Page.objects.create(
            space=self.space, title="Mail notes", body=f"[[ticket:{ticket.pk}]]"
        )
        add_link(self.agent, ("page", str(page.pk)), ("ticket", str(ticket.pk)), "blocks")

        save_page_links(page, self.agent)

        self.assertEqual(
            set(
                DynamicLink.objects.filter(source_type="page", source_id=str(page.pk)).values_list(
                    "relation", flat=True
                )
            ),
            {"blocks", "relates_to"},
        )

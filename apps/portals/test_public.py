"""The public portal pages: what a customer sees at ``/portal/<slug>/``."""

import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.portals.models import Portal
from apps.tickets.models import Ticket
from apps.wiki.models import Page, Space

STYLING = {
    "logo_url": "https://example.gov/logo.png",
    "accent": "coral",
    "custom_css": ".hero-title { color: red; } a::before { content: '</style>'; }",
    "hide_powered_by": True,
}


def styled(portal, **overrides):
    for field, value in STYLING.items():
        setattr(portal, field, overrides.get(field, value))
    portal.save()
    return portal


class HelpFrontDoorTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user("door-cust", "d@x.com", "pw", role="customer")
        self.client.force_login(self.customer)

    def test_help_redirects_to_the_default_portal(self):
        response = self.client.get(reverse("help:home"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/portal/help/")

    def test_help_keeps_the_search_query_for_the_portal_search(self):
        portal = self.client.get(reverse("help:home"), {"q": "Printer"})
        self.assertEqual(portal.status_code, 302)
        self.assertEqual(portal.url, "/portal/help/?q=Printer")

        home_page = self.client.get(portal["Location"])
        self.assertContains(home_page, 'value="Printer"')

        results = self.client.get(reverse("portals:portal_search", args=["help"]), {"q": "Printer"})
        self.assertContains(results, "for “Printer”")

    def test_help_keeps_its_own_page_when_there_is_no_published_default_portal(self):
        Portal.objects.filter(is_default=True).update(is_published=False)
        response = self.client.get(reverse("help:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Help Center")

    def test_help_articles_and_legacy_links_still_work(self):
        space = Space.objects.create(name="Door")
        page = Page.objects.create(
            space=space,
            title="Permit office",
            body="Counter 4.",
            is_published_to_help_center=True,
        )
        article = self.client.get(reverse("help:article", args=[page.slug]))
        self.assertEqual(article.status_code, 200)
        self.assertContains(article, "Counter 4.")

        legacy = self.client.get(reverse("help:legacy", args=[page.slug]))
        self.assertEqual(legacy.status_code, 301)
        self.assertEqual(legacy["Location"], reverse("help:article", args=[page.slug]))


class PortalHomeTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user("home-cust", "h@x.com", "pw", role="customer")
        self.agent = User.objects.create_user("home-agt", "ha@x.com", "pw", role="agent")
        self.portal = Portal.objects.create(
            name="Service desk", slug="service-desk", is_published=True, intro="Ask us."
        )
        self.grounds = Space.objects.create(name="Grounds")
        self.offices = Space.objects.create(name="Offices")
        self.root = Page.objects.create(
            space=self.grounds,
            title="Report a hole",
            body="Asphalt.",
            is_published_to_help_center=True,
        )
        self.child = Page.objects.create(
            space=self.grounds,
            parent=self.root,
            title="Holes in car parks",
            body="Cones.",
            is_published_to_help_center=True,
        )
        self.office_page = Page.objects.create(
            space=self.offices,
            title="Waste collection day",
            body="Tuesdays.",
            is_published_to_help_center=True,
        )

    def portal_page(self, user, slug=None):
        self.client.force_login(user)
        return self.client.get(reverse("portals:portal", args=[slug or self.portal.slug]))

    def test_the_default_portal_url_redirects_there(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("portals:default"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/portal/help/")

    def test_portal_shows_intro_forms_spaces_and_my_tickets(self):
        self.portal.intro = "Welcome to **Civica**."
        self.portal.request_forms = ["report-a-hole", "unknown-form"]
        self.portal.spaces.set([self.grounds])
        self.portal.save()
        Ticket.objects.create(title="Bin not collected", description="x", created_by=self.customer)
        Ticket.objects.create(
            title="Old request", description="x", created_by=self.customer, status="closed"
        )

        with patch(
            "apps.portals.public.form_choices",
            return_value=[("report-a-hole", "Report a hole"), ("other", "Something else")],
        ):
            page = self.portal_page(self.customer)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Welcome to <strong>Civica</strong>.")
        self.assertContains(page, "/tickets/create/?form=report-a-hole")
        self.assertNotContains(page, "?form=unknown-form")
        self.assertNotContains(page, "?form=other")
        self.assertContains(page, "Holes in car parks")
        self.assertNotContains(page, "Waste collection day")
        self.assertContains(page, "Bin not collected")
        self.assertNotContains(page, "Old request")
        self.assertContains(page, "/my-tickets/")

    def test_portal_offers_a_plain_ticket_link_when_it_lists_no_forms(self):
        with patch("apps.portals.public.form_choices", return_value=[]):
            page = self.portal_page(self.customer)
        self.assertContains(page, "Open a ticket")

    def test_portal_limits_pages_to_its_spaces(self):
        unlimited = self.portal_page(self.customer)
        self.assertContains(unlimited, "Waste collection day")

        self.portal.spaces.set([self.grounds])
        limited = self.portal_page(self.customer)
        self.assertNotContains(limited, "Waste collection day")
        self.assertContains(limited, "Holes in car parks")

    def test_portal_says_nothing_here_yet_when_it_has_no_pages(self):
        Page.objects.update(is_published_to_help_center=False)
        page = self.portal_page(self.customer)
        self.assertContains(page, "No guides published yet.")

    def test_my_tickets_follows_show_my_tickets_and_the_role(self):
        Ticket.objects.create(title="Leaky tap", description="x", created_by=self.customer)

        page = self.portal_page(self.customer)
        self.assertContains(page, "Your requests")
        self.assertContains(page, "Leaky tap")

        self.portal.show_my_tickets = False
        self.portal.save()
        self.assertNotContains(self.portal_page(self.customer), "Your requests")

        self.portal.show_my_tickets = True
        self.portal.save()
        self.assertNotContains(self.portal_page(self.agent), "Your requests")

    def test_you_have_no_open_tickets_when_the_customer_has_none(self):
        page = self.portal_page(self.customer)
        self.assertContains(page, "Your requests")
        self.assertContains(page, "You have no open requests.")

    def test_unpublished_portal_404_for_customers_preview_for_staff(self):
        self.portal.is_published = False
        self.portal.save()

        self.assertEqual(self.portal_page(self.customer).status_code, 404)
        preview = self.portal_page(self.agent)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Draft: only staff can see this")

    def test_an_unknown_portal_is_404_for_everyone(self):
        for user in (self.customer, self.agent):
            with self.subTest(role=user.role):
                self.assertEqual(self.portal_page(user, slug="nope").status_code, 404)


class PortalSearchTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user("srch-cust", "s@x.com", "pw", role="customer")
        self.agent = User.objects.create_user("srch-agt", "sa@x.com", "pw", role="agent")
        self.portal = Portal.objects.create(
            name="Search desk", slug="search-desk", is_published=True
        )
        self.grounds = Space.objects.create(name="Grounds")
        self.offices = Space.objects.create(name="Offices")
        self.public = Page.objects.create(
            space=self.grounds,
            title="Pothole repair",
            body="Asphalt and cones.",
            is_published_to_help_center=True,
        )
        self.internal = Page.objects.create(
            space=self.grounds, title="Pothole contractor phone number", body="secret"
        )

    def search(self, user, **extra):
        self.client.force_login(user)
        return self.client.get(reverse("portals:portal_search", args=[self.portal.slug]), **extra)

    def test_search_respects_show_search_and_publication(self):
        page = self.search(self.customer, data={"q": "Pothole"})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "1 result for “Pothole”")
        self.assertContains(page, reverse("help:article", args=[self.public.slug]))
        self.assertNotContains(page, "contractor phone number")

        staff_page = self.search(self.agent, data={"q": "Pothole"})
        self.assertContains(staff_page, "contractor phone number")
        self.assertContains(staff_page, reverse("wiki:page_detail", args=[self.internal.slug]))

    def test_search_is_404_when_the_portal_hides_search(self):
        self.portal.show_search = False
        self.portal.save()
        for user in (self.customer, self.agent):
            with self.subTest(role=user.role):
                self.assertEqual(self.search(user, data={"q": "Pothole"}).status_code, 404)

    def test_a_search_matching_nothing_says_so(self):
        page = self.search(self.customer, data={"q": "zzz-nothing"})
        self.assertContains(page, "0 results for")

    def test_search_is_limited_to_the_portal_spaces(self):
        office_page = Page.objects.create(
            space=self.offices,
            title="Pothole inside the building",
            body="Trip hazard.",
            is_published_to_help_center=True,
        )
        self.assertContains(self.search(self.customer, data={"q": "Pothole"}), office_page.title)

        self.portal.spaces.set([self.grounds])
        limited = self.search(self.customer, data={"q": "Pothole"})
        self.assertNotContains(limited, office_page.title)
        self.assertContains(limited, self.public.title)


class StylingTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user("sty-cust", "st@x.com", "pw", role="customer")
        self.client.force_login(self.customer)
        self.portal = styled(Portal.objects.get(slug="help"))

    def home(self):
        return self.client.get(reverse("portals:portal", args=["help"]))

    def test_styling_only_applies_with_portal_branding(self):
        without = self.home()
        self.assertNotContains(without, "color: red")
        self.assertNotContains(without, "tc-coral")
        self.assertNotContains(without, STYLING["logo_url"])

        with patch("apps.portals.public.styling_enabled", return_value=True):
            page = self.home()
        self.assertContains(page, '<section class="hc-hero tc-coral fade-in d1">')
        self.assertContains(page, STYLING["logo_url"])
        body = page.content.decode()
        self.assertIn(".hero-title { color: red; }", body)
        self.assertNotIn("'</style>'", body)
        self.assertIn("\\3c /style&gt;", body)

    def test_lavender_accent_is_the_lav_tint(self):
        self.portal.accent = "lavender"
        self.portal.save()
        with patch("apps.portals.public.styling_enabled", return_value=True):
            self.assertContains(self.home(), '<section class="hc-hero tc-lav fade-in d1">')

    def test_powered_by_hidden_only_when_styled(self):
        self.assertContains(self.home(), "Powered by Jackil")

        with patch("apps.portals.public.styling_enabled", return_value=True):
            self.assertNotContains(self.home(), "Powered by Jackil")

    def test_powered_by_shows_when_styled_but_not_hidden(self):
        self.portal.hide_powered_by = False
        self.portal.save()
        with patch("apps.portals.public.styling_enabled", return_value=True):
            self.assertContains(self.home(), "Powered by Jackil")


class AccessTests(TestCase):
    def test_anonymous_is_sent_to_login(self):
        for url in (
            reverse("portals:default"),
            reverse("portals:portal", args=["help"]),
            reverse("portals:portal_search", args=["help"]),
            reverse("help:home"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response.url)


class HelpCenterRedesignTests(TestCase):
    """M14: the Help center hero, live search, and staff-only pinning."""

    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("aria", password="x", role="agent")
        cls.customer = User.objects.create_user("cust", password="x", role="customer")
        cls.space = Space.objects.create(name="Getting connected")
        cls.other = Space.objects.create(name="Your account")
        Page.objects.create(
            space=cls.space,
            title="Connect to the office Wi-Fi",
            body="wifi",
            is_published_to_help_center=True,
        )
        Page.objects.create(space=cls.space, title="Internal VPN notes", body="wifi secrets")
        cls.portal = Portal.objects.create(name="IT help", slug="it-help", is_published=True)

    def test_hero_has_search_and_both_buttons(self):
        self.client.force_login(self.customer)
        page = self.client.get(reverse("portals:portal", args=["it-help"]))
        self.assertContains(page, "How can we <em>help?</em>")
        self.assertContains(page, "Open a ticket")
        self.assertContains(page, 'data-suggest="/portal/it-help/suggest/"')

    def test_customer_sees_no_pin_controls(self):
        self.client.force_login(self.customer)
        page = self.client.get(reverse("portals:portal", args=["it-help"]))
        self.assertNotContains(page, "data-pin")
        self.assertNotContains(page, "Arrange this page")

    def test_staff_see_the_arrange_bar(self):
        self.client.force_login(self.agent)
        page = self.client.get(reverse("portals:portal", args=["it-help"]))
        self.assertContains(page, "Arrange this page")
        self.assertContains(page, 'data-pins-url="/portal/it-help/pins/"')

    def test_suggest_returns_only_published_guides(self):
        self.client.force_login(self.customer)
        body = self.client.get(
            reverse("portals:portal_suggest", args=["it-help"]), {"q": "wifi"}
        ).json()
        self.assertEqual([g["title"] for g in body["guides"]], ["Connect to the office Wi-Fi"])

    def test_pins_save_order_and_spaces_for_staff(self):
        self.client.force_login(self.agent)
        response = self.client.post(
            reverse("portals:portal_pins", args=["it-help"]),
            data=json.dumps({"forms": [], "spaces": [self.other.pk, self.space.pk]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.portal.refresh_from_db()
        self.assertEqual(self.portal.space_order, [self.other.pk, self.space.pk])
        self.assertEqual(
            set(self.portal.spaces.values_list("pk", flat=True)), {self.other.pk, self.space.pk}
        )

    def test_pins_refuse_customers_and_anonymous(self):
        url = reverse("portals:portal_pins", args=["it-help"])
        payload = json.dumps({"forms": [], "spaces": [self.space.pk]})
        self.assertNotEqual(
            self.client.post(url, data=payload, content_type="application/json").status_code, 200
        )
        self.client.force_login(self.customer)
        self.assertEqual(
            self.client.post(url, data=payload, content_type="application/json").status_code, 403
        )
        self.portal.refresh_from_db()
        self.assertFalse(self.portal.spaces.exists())

    def test_open_a_ticket_about_prefills_the_title(self):
        self.client.force_login(self.customer)
        page = self.client.get(reverse("tickets:ticket_create"), {"title": "printer jams"})
        self.assertContains(page, 'value="printer jams"')


class SuggestHyphenTests(TestCase):
    def test_wifi_finds_wi_fi(self):
        customer = User.objects.create_user("cust2", password="x", role="customer")
        space = Space.objects.create(name="Net")
        Page.objects.create(
            space=space, title="Connect to the Wi-Fi", body="x", is_published_to_help_center=True
        )
        Portal.objects.create(name="Desk", slug="desk", is_published=True)
        self.client.force_login(customer)
        body = self.client.get(
            reverse("portals:portal_suggest", args=["desk"]), {"q": "wifi"}
        ).json()
        self.assertEqual([g["title"] for g in body["guides"]], ["Connect to the Wi-Fi"])

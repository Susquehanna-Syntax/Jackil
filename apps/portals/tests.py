"""The Portal model and the admin portal pages."""

from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.portals import service
from apps.portals.forms import PortalForm, parse_status_pages
from apps.portals.models import Portal
from apps.wiki.models import Space

STYLING = {
    "logo_url": "https://example.gov/logo.png",
    "accent": "coral",
    "custom_css": ".portal { color: red; }",
    "hide_powered_by": "on",
}


def base_data(**overrides):
    data = {
        "name": "Service desk",
        "slug": "service-desk",
        "intro": "",
        "request_forms": [],
        "spaces": [],
        "show_search": "on",
        "show_my_tickets": "on",
        "vigil_status_pages": "",
        # Left out of a POST, ModelForms treat these required fields as empty.
        "accent": "lavender",
        "department": "",
    }
    data.update(overrides)
    return data


def messages_from(response):
    return [(m.level_tag, str(m)) for m in get_messages(response.wsgi_request)]


class PortalModelTests(TestCase):
    def test_default_portal_exists_after_migrate(self):
        help_center = Portal.objects.get(slug="help")
        self.assertEqual(help_center.name, "Help center")
        self.assertTrue(help_center.is_published)
        self.assertTrue(help_center.is_default)

    def test_only_one_default_portal(self):
        second = Portal.objects.create(name="Second", slug="second", is_default=True)

        self.assertTrue(Portal.objects.get(slug="second").is_default)
        self.assertFalse(Portal.objects.get(slug="help").is_default)
        self.assertEqual(Portal.objects.filter(is_default=True).count(), 1)

        help_center = Portal.objects.get(slug="help")
        help_center.is_default = True
        help_center.save()
        self.assertTrue(Portal.objects.get(pk=second.pk).is_default is False)
        self.assertEqual(Portal.objects.filter(is_default=True).count(), 1)

    def test_reserved_slug_is_refused(self):
        for slug in ("new", "admin", "api", "static"):
            with self.subTest(slug=slug):
                with self.assertRaises(ValidationError):
                    Portal(name="Nope", slug=slug).clean()


class ServiceTests(TestCase):
    def test_form_choices_empty_without_customfields(self):
        with patch("apps.portals.service.feature_enabled", return_value=False):
            self.assertEqual(service.form_choices(), [])

    def test_form_choices_lists_active_forms_with_customfields(self):
        class FakeForm:
            slug = "report-a-hole"
            name = "Report a hole"

        with (
            patch("apps.portals.service.feature_enabled", return_value=True),
            patch("apps.customfields.service.active_forms", return_value=iter([FakeForm()])),
        ):
            self.assertEqual(service.form_choices(), [("report-a-hole", "Report a hole")])

    def test_can_add_portal_needs_the_first_portal_or_the_feature(self):
        self.assertFalse(service.can_add_portal())

        with patch("apps.portals.service.feature_enabled", return_value=True):
            self.assertTrue(service.can_add_portal())


class PortalListTests(TestCase):
    def setUp(self):
        self.url = "/settings/portals/"
        self.admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")

    def test_list_shows_the_default_portal_and_the_business_hint(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Portals")
        self.assertContains(response, "Help center")
        self.assertContains(response, "/portal/help/")
        self.assertContains(response, "Published")
        self.assertContains(response, "Default")
        self.assertContains(response, "More than one portal is part of SQSY Business.")

    def test_list_offers_new_portal_when_the_feature_is_on(self):
        self.client.force_login(self.admin)
        with patch("apps.portals.service.feature_enabled", return_value=True):
            response = self.client.get(self.url)
        self.assertNotContains(response, "More than one portal is part of SQSY Business.")
        self.assertContains(response, "/settings/portals/new/")


class SecondPortalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")
        self.client.force_login(self.admin)

    def test_second_portal_needs_portal_branding(self):
        response = self.client.post("/settings/portals/new/", base_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/settings/portals/")
        self.assertEqual(Portal.objects.count(), 1)
        self.assertIn(
            ("error", "More than one portal is part of SQSY Business."),
            messages_from(response),
        )

    def test_second_portal_is_created_with_the_feature(self):
        with patch("apps.portals.service.feature_enabled", return_value=True):
            response = self.client.post("/settings/portals/new/", base_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Portal.objects.count(), 2)
        portal = Portal.objects.get(slug="service-desk")
        self.assertFalse(portal.is_default)
        self.assertEqual(response.url, f"/settings/portals/{portal.pk}/")


class StylingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")
        self.client.force_login(self.admin)
        self.portal = Portal.objects.get(slug="help")
        self.url = f"/settings/portals/{self.portal.pk}/"

    def test_styling_fields_are_ignored_without_the_feature(self):
        self.client.post(self.url, base_data(slug="help", name="Help center", **STYLING))
        self.portal.refresh_from_db()
        self.assertEqual(self.portal.custom_css, "")
        self.assertEqual(self.portal.accent, "lavender")
        self.assertFalse(self.portal.hide_powered_by)

    def test_styling_fields_save_with_the_feature(self):
        with patch("apps.portals.service.feature_enabled", return_value=True):
            self.client.post(self.url, base_data(slug="help", name="Help center", **STYLING))
        self.portal.refresh_from_db()
        self.assertEqual(self.portal.custom_css, ".portal { color: red; }")
        self.assertEqual(self.portal.accent, "coral")
        self.assertTrue(self.portal.hide_powered_by)

    def test_edit_page_shows_the_business_hint_without_the_feature(self):
        response = self.client.get(self.url)
        self.assertContains(response, "part of SQSY Business")
        self.assertNotContains(response, "id_custom_css")


class VigilStatusPagesTests(TestCase):
    def test_vigil_status_pages_parse_and_validate(self):
        self.assertEqual(parse_status_pages(" mail , portal,, "), ["mail", "portal"])
        self.assertEqual(parse_status_pages(""), [])

        with self.assertRaises(ValidationError) as ctx:
            parse_status_pages(",".join(f"page-{i}" for i in range(11)))
        self.assertIn(
            "Use up to ten Vigil status-page slugs, separated by commas.",
            str(ctx.exception),
        )

        with self.assertRaises(ValidationError):
            parse_status_pages("not a slug!")

    def test_ten_slugs_are_allowed_and_blanks_are_dropped(self):
        ten = [f"page-{i}" for i in range(10)]
        self.assertEqual(parse_status_pages(", ,".join(ten)), ten)

    def test_form_saves_the_slug_list(self):
        admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")
        self.client.force_login(admin)
        portal = Portal.objects.get(slug="help")

        response = self.client.post(
            f"/settings/portals/{portal.pk}/",
            base_data(slug="help", name="Help center", vigil_status_pages="mail, portal"),
        )
        self.assertEqual(response.status_code, 302)
        portal.refresh_from_db()
        self.assertEqual(portal.vigil_status_pages, ["mail", "portal"])

        response = self.client.post(
            f"/settings/portals/{portal.pk}/",
            base_data(slug="help", name="Help center", vigil_status_pages="bad slug"),
        )
        self.assertEqual(response.status_code, 200)
        portal.refresh_from_db()
        self.assertEqual(portal.vigil_status_pages, ["mail", "portal"])


class DeletePortalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")
        self.client.force_login(self.admin)
        self.help_center = Portal.objects.get(slug="help")

    def test_cannot_delete_the_default_portal(self):
        response = self.client.post(f"/settings/portals/{self.help_center.pk}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Portal.objects.filter(pk=self.help_center.pk).exists())
        self.assertIn(("error", "Make another portal the default first."), messages_from(response))

    def test_a_non_default_portal_deletes(self):
        second = Portal.objects.create(name="Second", slug="second")
        response = self.client.post(f"/settings/portals/{second.pk}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Portal.objects.filter(pk=second.pk).exists())

    def test_a_get_is_not_a_delete(self):
        second = Portal.objects.create(name="Second", slug="second")
        response = self.client.get(f"/settings/portals/{second.pk}/delete/")
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Portal.objects.filter(pk=second.pk).exists())


class AccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")
        self.agent = User.objects.create_user("agt", "agt@x.com", "pass", role="agent")
        self.customer = User.objects.create_user("cust", "cust@x.com", "pass", role="customer")

    def test_portal_pages_admin_only(self):
        self.portal = Portal.objects.get(slug="help")
        urls = [
            "/settings/portals/",
            "/settings/portals/new/",
            f"/settings/portals/{self.portal.pk}/",
            f"/settings/portals/{self.portal.pk}/delete/",
        ]
        for url in urls:
            for user in (self.agent, self.customer):
                with self.subTest(url=url, role=user.role):
                    self.client.force_login(user)
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 302)
                    self.assertNotIn("/settings/portals/", response.url)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(urls[0]).status_code, 200)


class PortalFormTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("adm", "adm@x.com", "pass", role="admin")
        self.client.force_login(self.admin)

    def test_reserved_slug_is_refused_by_the_form(self):
        form = PortalForm(data=base_data(slug="admin"))
        self.assertFalse(form.is_valid())
        self.assertIn("slug", form.errors)

    def test_a_saved_portal_shows_its_link_text_and_can_be_edited(self):
        with patch("apps.portals.service.feature_enabled", return_value=True):
            created = self.client.post("/settings/portals/new/", base_data())
        portal = Portal.objects.get(slug="service-desk")

        listing = self.client.get("/settings/portals/")
        self.assertContains(listing, "/portal/service-desk/")
        self.assertEqual(listing.status_code, 200)

        page = self.client.get(f"/settings/portals/{portal.pk}/")
        self.assertContains(page, "/portal/service-desk/")
        self.assertContains(page, "Delete portal")
        self.assertNotContains(page, "More than one portal is part of SQSY Business.")
        self.assertEqual(created.status_code, 302)

    def test_spaces_can_be_chosen_and_shown_in_the_edit_page(self):
        space = Space.objects.first()
        if space is None:
            self.skipTest("the wiki migrations seeded no spaces")
        portal = Portal.objects.get(slug="help")

        self.client.post(
            f"/settings/portals/{portal.pk}/",
            base_data(slug="help", name="Help center", spaces=[str(space.pk)]),
        )
        portal.refresh_from_db()
        self.assertEqual(list(portal.spaces.all()), [space])

        page = self.client.get(f"/settings/portals/{portal.pk}/")
        self.assertContains(page, space.name)


class EditFormTests(TestCase):
    def test_saved_status_pages_show_as_text_and_save_round_trips(self):
        from apps.portals.forms import PortalForm
        from apps.portals.models import Portal

        portal = Portal.objects.get(is_default=True)
        portal.vigil_status_pages = ["mail", "vpn"]
        portal.save()
        form = PortalForm(instance=portal)
        self.assertEqual(form.initial["vigil_status_pages"], "mail, vpn")
        empty = Portal.objects.create(name="Empty", slug="empty-check")
        self.assertEqual(PortalForm(instance=empty).initial["vigil_status_pages"], "")

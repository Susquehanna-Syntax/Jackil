"""The dashboard page and the vendored grid assets."""

import hashlib
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.dashboards import contract


def _static(relpath):
    return (Path(settings.BASE_DIR) / "static" / relpath).read_text()


class DashboardPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("pageagent", "pa@x.com", "pw", role="agent")
        cls.customer = User.objects.create_user("pagecust", "pc@x.com", "pw", role="customer")

    def test_agent_lands_on_the_widget_dashboard(self):
        self.client.force_login(self.agent)
        resp = self.client.get(reverse("tickets:dashboard"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('id="dash-root"', body)
        self.assertIn("js/jackil-dashboards.js", body)
        self.assertIn("js/vendor/gridstack-all.js", body)
        self.assertIn("css/vendor/gridstack.min.css", body)
        self.assertIn("csrftoken", resp.cookies)

    def test_customer_is_still_redirected(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("tickets:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("tickets:customer_tickets"))

    def test_anonymous_sees_public_page(self):
        resp = self.client.get(reverse("tickets:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "tickets/dashboard_public.html")


class EditModeTests(SimpleTestCase):
    """Edit mode is a set of named functions wired to the toolbar, so these
    tests pin the wiring rather than rendering anything."""

    def test_edit_mode_is_wired(self):
        js = _static("js/jackil-dashboards.js")
        for name in (
            "_dashSaveLayout",
            "_dashCollectLayout",
            "openWidgetCatalog",
            "JackilModal.prompt",
            "JackilModal.confirm",
            "/layout/",
        ):
            self.assertIn(name, js)

    def test_edit_buttons_are_not_rendered_on_a_narrow_screen(self):
        """A one-column grid is a phone's layout. Arranging it and saving would
        overwrite the real twelve-column one, so the whole #dash-actions block
        is skipped below DASH_NARROW — which means the toolbar function itself
        has to name the threshold."""
        js = _static("js/jackil-dashboards.js")
        self.assertIn("DASH_NARROW", js)
        toolbar = js[js.index("function _dashToolbar() {") :]
        self.assertIn("DASH_NARROW", toolbar[: toolbar.index("\n}\n")])

    def test_a_narrow_grid_never_saves_its_layout(self):
        """Saving is refused while the grid is narrower than the registry's, and
        the guard is on the save path itself — not only on the button that would
        have started the edit."""
        js = _static("js/jackil-dashboards.js")
        body = js[js.index("async function _dashSaveLayout() {") :]
        self.assertIn("getColumn()", body)


class LayoutCollectionTests(SimpleTestCase):
    def test_layout_is_read_from_live_nodes(self):
        """Gridstack's save() drops w/h for a widget at its minimum — see
        Vigil's comment in _dashCollectLayout — so nothing may call it."""
        js = _static("js/jackil-dashboards.js")
        self.assertIn("gridstackNode", js)
        self.assertNotIn(".save(", js)


class WidgetSettingsTests(SimpleTestCase):
    def test_settings_form_has_saved_view_picker(self):
        js = _static("js/jackil-widgets.js")
        self.assertIn("saved_view", js)
        self.assertIn("/dashboards/api/options/saved_view/", js)


class OldDashboardGoneTests(TestCase):
    """The fixed dashboard and its profile preference are deleted, not hidden."""

    def test_profile_has_no_needs_attention_toggle(self):
        user = User.objects.create_user("dana", "dana@x.com", "password123", role="agent")
        self.client.force_login(user)
        resp = self.client.get(reverse("accounts:profile"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("show_needs_attention", resp.content.decode())

    def test_old_dashboard_template_is_gone(self):
        self.assertFalse((Path(settings.BASE_DIR) / "templates/tickets/dashboard.html").exists())


class VendorTests(SimpleTestCase):
    def test_gridstack_is_the_pinned_build(self):
        digest = hashlib.sha256(
            (Path(settings.BASE_DIR) / "static/js/vendor/gridstack-all.js").read_bytes()
        ).hexdigest()
        self.assertEqual(digest, "6e3032a6906805e43ca7e2dc818989b170bb65b686a6d0e89e6b68ad61f5946f")

    def test_widget_renderers_cover_every_shape(self):
        js = _static("js/jackil-widgets.js")
        for shape in contract.SHAPES:
            self.assertIn(f"{shape}:", js)
        self.assertGreaterEqual(js.count("WIDGET_SHAPES"), 2)

    def test_renderers_escape(self):
        js = _static("js/jackil-widgets.js")
        self.assertGreaterEqual(js.count("escHtml("), 8)

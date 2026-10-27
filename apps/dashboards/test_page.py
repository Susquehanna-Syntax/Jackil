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

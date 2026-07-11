import json
from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User
from apps.api.models import ApiKey, Webhook
from apps.tickets.models import Ticket


class ApiKeyAuthTests(TestCase):
    def setUp(self):
        self.agent = User.objects.create_user("agent", "a@x.com", "p", role="agent")
        self.key = ApiKey.objects.create(name="test", user=self.agent)
        self.customer = User.objects.create_user("cust", "c@x.com", "p", role="customer")
        Ticket.objects.create(
            title="T1", description="d", created_by=self.customer, priority="high"
        )

    def _auth(self, key=None):
        return {"HTTP_AUTHORIZATION": f"Api-Key {key or self.key.key}"}

    def test_list_tickets_with_valid_key(self):
        r = self.client.get("/api/v1/tickets/", **self._auth())
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()["count"], 1)

    def test_missing_key_is_unauthorized(self):
        r = self.client.get("/api/v1/tickets/")
        self.assertin_status(r.status_code)

    def assertin_status(self, code):
        self.assertIn(code, (401, 403))

    def test_invalid_key_rejected(self):
        r = self.client.get("/api/v1/tickets/", HTTP_AUTHORIZATION="Api-Key bogus")
        self.assertEqual(r.status_code, 401)

    def test_customer_key_forbidden(self):
        ckey = ApiKey.objects.create(name="c", user=self.customer)
        r = self.client.get("/api/v1/tickets/", HTTP_AUTHORIZATION=f"Api-Key {ckey.key}")
        self.assertEqual(r.status_code, 403)

    def test_create_ticket_via_api(self):
        r = self.client.post(
            "/api/v1/tickets/",
            data=json.dumps({"title": "API ticket", "description": "made via api"}),
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(r.status_code, 201)
        t = Ticket.objects.get(title="API ticket")
        self.assertEqual(t.source, "api")
        self.assertEqual(t.created_by, self.agent)

    def test_post_message_via_api(self):
        ticket = Ticket.objects.first()
        r = self.client.post(
            f"/api/v1/tickets/{ticket.id}/messages/",
            data=json.dumps({"body": "hello from api", "kind": "reply"}),
            content_type="application/json",
            **self._auth(),
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(ticket.messages.filter(body="hello from api").exists())

    def test_key_masked_and_generated(self):
        self.assertTrue(self.key.key)
        self.assertIn("…", self.key.masked)


class ApiHardeningTests(TestCase):
    def setUp(self):
        self.agent = User.objects.create_user("hagent", "h@x.com", "p", role="agent")
        self.key = ApiKey.objects.create(name="h", user=self.agent)
        self.customer = User.objects.create_user("hcust", "hc@x.com", "p", role="customer")
        for i in range(5):
            Ticket.objects.create(
                title=f"T{i}", description="d", created_by=self.customer, priority="low"
            )

    def _auth(self):
        return {"HTTP_AUTHORIZATION": f"Api-Key {self.key.key}"}

    def test_page_size_query_param_honored(self):
        r = self.client.get("/api/v1/tickets/?page_size=2", **self._auth())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["results"]), 2)

    def test_page_size_cap_enforced(self):
        from apps.api.pagination import StandardPagination

        self.assertEqual(StandardPagination.max_page_size, 100)
        self.assertEqual(StandardPagination.page_size_query_param, "page_size")

    def test_throttle_settings_configured(self):
        from django.conf import settings

        self.assertIn("DEFAULT_THROTTLE_RATES", settings.REST_FRAMEWORK)
        self.assertIn("user", settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])


class WebhookTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user("cust", "c@x.com", "p", role="customer")

    @patch("apps.api.webhooks.urllib.request.urlopen")
    def test_webhook_fires_on_ticket_created(self, mock_open):
        mock_open.return_value.__enter__.return_value.status = 200
        Webhook.objects.create(name="hook", url="https://example.com/hook", event="ticket.created")
        Ticket.objects.create(title="Hooked", description="d", created_by=self.customer)
        self.assertTrue(mock_open.called)
        hook = Webhook.objects.first()
        hook.refresh_from_db()
        self.assertEqual(hook.last_status, "200")

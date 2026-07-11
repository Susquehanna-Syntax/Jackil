from django.test import Client, TestCase

from apps.accounts.models import User
from apps.tickets.models import SavedView


class SavedViewTests(TestCase):
    """Tests for SavedView CRUD and ticket-list integration."""

    def setUp(self):
        self.agent_a = User.objects.create_user(
            username="agent_a", email="a@t.com", password="p", role="agent"
        )
        self.agent_b = User.objects.create_user(
            username="agent_b", email="b@t.com", password="p", role="agent"
        )
        self.client = Client(SERVER_NAME="localhost")

    def test_create_saves_view_for_owner(self):
        self.client.force_login(self.agent_a)
        self.client.post(
            "/tickets/views/save/",
            {"name": "My open", "query": "status=open&priority=high"},
        )
        v = SavedView.objects.get(name="My open")
        self.assertEqual(v.owner, self.agent_a)
        self.assertEqual(v.query, "status=open&priority=high")

    def test_create_requires_name(self):
        self.client.force_login(self.agent_a)
        self.client.post(
            "/tickets/views/save/",
            {"name": "", "query": "status=open"},
        )
        self.assertFalse(SavedView.objects.exists())

    def test_list_shows_own_view(self):
        self.client.force_login(self.agent_a)
        SavedView.objects.create(name="My open", owner=self.agent_a, query="status=open")
        r = self.client.get("/tickets/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"My open", r.content)

    def test_delete_own_view(self):
        self.client.force_login(self.agent_a)
        v = SavedView.objects.create(name="Del me", owner=self.agent_a, query="")
        self.client.post(f"/tickets/views/{v.pk}/delete/")
        self.assertFalse(SavedView.objects.filter(pk=v.pk).exists())

    def test_delete_others_view_forbidden(self):
        self.client.force_login(self.agent_a)
        v = SavedView.objects.create(name="A view", owner=self.agent_a, query="")
        self.client.force_login(self.agent_b)
        r = self.client.post(f"/tickets/views/{v.pk}/delete/")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(SavedView.objects.filter(pk=v.pk).exists())

    def test_shared_view_visible_to_other_agent(self):
        self.client.force_login(self.agent_a)
        SavedView.objects.create(name="Shared", owner=self.agent_a, query="", is_shared=True)
        SavedView.objects.create(name="Private", owner=self.agent_a, query="", is_shared=False)
        self.client.force_login(self.agent_b)
        r = self.client.get("/tickets/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Shared", r.content)
        self.assertNotIn(b"Private", r.content)

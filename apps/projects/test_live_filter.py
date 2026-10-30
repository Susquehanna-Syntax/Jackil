"""A project's issue list filters as you type through the partial endpoint."""

from django.test import TestCase

from apps.accounts.models import User
from apps.projects import service


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@x.com", "pw", role=role)


class IssueLiveFilterTests(TestCase):
    def setUp(self):
        self.admin = make_user("coral", "admin")
        self.client.force_login(self.admin)
        self.project = service.create_project(self.admin, "NET", "Field Networking", "scrum")
        service.create_issue(self.admin, self.project, title="Replace the edge switch")
        service.create_issue(self.admin, self.project, title="Label the patch panels")

    def test_issue_partial_filters_by_title(self):
        response = self.client.get(f"/projects/{self.project.key}/?q=switch&partial=1")
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Replace the edge switch", body)
        self.assertNotIn("Label the patch panels", body)
        self.assertNotIn("<html", body)

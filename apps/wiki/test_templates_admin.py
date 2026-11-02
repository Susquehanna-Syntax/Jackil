"""The admin screens for page templates."""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.wiki.models import PageTemplate


class TemplateAdminTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("admin1", password="x", role="admin")
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.customer = User.objects.create_user("cust1", password="x", role="customer")

    def template(self, name="Escalation notes", **kwargs):
        return PageTemplate.objects.create(name=name, body="## What happened", **kwargs)

    def builtin(self, name):
        """The migration's built-in row, under the name the migration wrote."""
        return PageTemplate.objects.get(name=name, is_builtin=True)

    def post_template(self, url, *, name="Escalation notes", body="## What happened", **extra):
        return self.client.post(url, {"name": name, "body": body, **extra})

    def test_admin_creates_edits_and_deletes_a_template(self):
        self.client.force_login(self.admin)
        before = PageTemplate.objects.count()

        created = self.post_template(
            reverse("wiki:template_create"),
            name="VPN troubleshooting",
            body="# Symptom\n\n# Steps",
            description="The usual VPN dance",
        )
        self.assertEqual(created.status_code, 302)
        self.assertEqual(created.url, reverse("wiki:template_list"))
        self.assertEqual(PageTemplate.objects.count(), before + 1)

        template = PageTemplate.objects.get(name="VPN troubleshooting")
        self.assertEqual(template.description, "The usual VPN dance")
        self.assertEqual(template.body, "# Symptom\n\n# Steps")
        self.assertFalse(template.is_builtin)

        # It is offered to whoever starts a page.
        editor = self.client.get(reverse("wiki:page_new")).content.decode()
        self.assertIn(f'value="{template.pk}"', editor)

        edited = self.post_template(
            reverse("wiki:template_edit", args=[template.pk]),
            name="VPN troubleshooting",
            body="# Symptom\n\n# Steps\n\n# Escalation",
        )
        self.assertEqual(edited.status_code, 302)
        template.refresh_from_db()
        self.assertIn("# Escalation", template.body)

        # The list names it and offers both actions.
        listing = self.client.get(reverse("wiki:template_list")).content.decode()
        self.assertIn("VPN troubleshooting", listing)
        self.assertIn(reverse("wiki:template_edit", args=[template.pk]), listing)
        self.assertIn(reverse("wiki:template_delete", args=[template.pk]), listing)

        # A name already taken is refused, and the count says so.
        clash = self.post_template(reverse("wiki:template_create"), name="VPN troubleshooting")
        self.assertEqual(clash.status_code, 200)
        self.assertIn("already a template with that name", clash.content.decode())
        self.assertEqual(PageTemplate.objects.count(), before + 1)

        # A template with no body is not a template.
        empty = self.post_template(reverse("wiki:template_create"), name="No body", body="   ")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(PageTemplate.objects.count(), before + 1)

        deleted = self.client.post(reverse("wiki:template_delete", args=[template.pk]))
        self.assertEqual(deleted.status_code, 302)
        self.assertFalse(PageTemplate.objects.filter(pk=template.pk).exists())

    def test_builtin_template_cannot_be_deleted(self):
        builtin = self.builtin("Runbook")
        self.client.force_login(self.admin)

        shown = self.client.get(reverse("wiki:template_delete", args=[builtin.pk]))
        self.assertEqual(shown.status_code, 302)
        self.assertEqual(shown.url, reverse("wiki:template_list"))
        self.assertTrue(PageTemplate.objects.filter(pk=builtin.pk).exists())

        refused = self.client.post(reverse("wiki:template_delete", args=[builtin.pk]))
        self.assertEqual(refused.status_code, 302)
        self.assertTrue(PageTemplate.objects.filter(pk=builtin.pk).exists())

        # The list says which ones are built in, and a built-in is still editable.
        listing = self.client.get(reverse("wiki:template_list")).content.decode()
        self.assertIn("built-in", listing)
        edited = self.post_template(
            reverse("wiki:template_edit", args=[builtin.pk]),
            name="Runbook",
            body="# Steps\n\n# Rollback",
        )
        self.assertEqual(edited.status_code, 302)
        builtin.refresh_from_db()
        self.assertEqual(builtin.body, "# Steps\n\n# Rollback")
        self.assertTrue(builtin.is_builtin)

    def test_agent_and_customer_get_403(self):
        builtin = self.builtin("Runbook")
        urls = [
            reverse("wiki:template_list"),
            reverse("wiki:template_create"),
            reverse("wiki:template_edit", args=[builtin.pk]),
            reverse("wiki:template_delete", args=[builtin.pk]),
        ]
        for user in (self.agent, self.customer):
            self.client.force_login(user)
            for url in urls:
                self.assertEqual(
                    self.client.get(url).status_code,
                    403,
                    f"{user.role} should be refused {url}",
                )
                self.assertEqual(
                    self.client.post(url, {"name": "Sneaky", "body": "x"}).status_code,
                    403,
                    f"{user.role} should be refused posting {url}",
                )
        self.assertEqual(PageTemplate.objects.filter(name="Sneaky").count(), 0)

    def test_anonymous_is_sent_to_sign_in(self):
        response = self.client.get(reverse("wiki:template_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_the_wiki_home_links_templates_for_admins_only(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("wiki:home")).content.decode()
        self.assertIn(reverse("wiki:template_list"), body)

        self.client.force_login(self.agent)
        body = self.client.get(reverse("wiki:home")).content.decode()
        self.assertNotIn(reverse("wiki:template_list"), body)

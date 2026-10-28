"""Escalating helpdesk tickets into project issues."""

from django.urls import reverse

from apps.links.models import DynamicLink
from apps.projects.models import Issue
from apps.projects.test_backlog import BacklogTest
from apps.tickets.models import Ticket, TicketMessage


class EscalateTests(BacklogTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create(
            title="Printer on fire",
            description="Line one\nLine two",
            created_by=self.customer,
        )

    def escalate(self, user, **payload):
        self.login(user)
        data = {"project": "NET"}
        data.update(payload)
        return self.client.post(reverse("projects:escalate", args=[self.ticket.pk]), data)

    def system_notes(self):
        return TicketMessage.objects.filter(ticket=self.ticket, kind="system")

    def test_escalate_creates_an_issue_links_both_ways_and_notes_the_ticket(self):
        response = self.escalate(self.agent, type="bug", title="")
        issue = Issue.objects.get(project=self.project, title="Printer on fire")
        self.assertRedirects(response, reverse("projects:issue_detail", args=[issue.key]))
        self.assertEqual(issue.type, "bug")
        self.assertTrue(issue.description.startswith(f"Escalated from ticket #{self.ticket.pk}."))
        self.assertIn("> Line two", issue.description)
        self.assertTrue(
            DynamicLink.objects.filter(
                source_type="ticket",
                source_id=str(self.ticket.pk),
                target_type="card",
                target_id=str(issue.pk),
                relation="fixed_by",
            ).exists()
        )
        self.assertTrue(self.system_notes().filter(body=f"Escalated to {issue.key}").exists())

    def test_escalate_unknown_or_archived_project_creates_nothing(self):
        before = Issue.objects.count()
        missing = self.escalate(self.agent, project="NOPE", type="task", title="X")
        self.assertRedirects(missing, reverse("tickets:ticket_detail", args=[self.ticket.pk]))

        self.project.is_archived = True
        self.project.save(update_fields=["is_archived"])
        archived = self.escalate(self.agent, project="NET", type="task", title="X")
        self.assertRedirects(archived, reverse("tickets:ticket_detail", args=[self.ticket.pk]))

        self.assertEqual(Issue.objects.count(), before)
        self.assertFalse(self.system_notes().exists())

    def test_escalate_bad_type_falls_back_to_task(self):
        self.escalate(self.agent, type="epic", title="Carry over")
        self.assertEqual(Issue.objects.get(title="Carry over").type, "task")

    def test_escalate_customer_403(self):
        before = Issue.objects.count()
        response = self.escalate(self.customer, type="bug", title="Nope")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Issue.objects.count(), before)

    def test_escalate_get_is_405(self):
        self.login(self.agent)
        response = self.client.get(reverse("projects:escalate", args=[self.ticket.pk]))
        self.assertEqual(response.status_code, 405)

    def test_ticket_page_offers_escalation_to_staff_only(self):
        detail = reverse("tickets:ticket_detail", args=[self.ticket.pk])
        self.login(self.agent)
        staff_page = self.client.get(detail).content.decode()
        self.assertIn("escalate_modal", staff_page)
        self.assertIn("NET", staff_page)

        self.login(self.customer)
        customer_page = self.client.get(detail).content.decode()
        self.assertNotIn("escalate_modal", customer_page)

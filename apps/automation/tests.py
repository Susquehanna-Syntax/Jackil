from django.test import TestCase

from apps.accounts.models import User
from apps.automation.engine import apply_actions, rule_matches, run_rules
from apps.automation.models import AutomationRule
from apps.tickets.models import Ticket, TicketMessage


class RuleMatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", "u@x.com", "p")
        self.ticket = Ticket.objects.create(
            title="VPN is down", description="urgent", created_by=self.user, priority="high"
        )

    def test_eq_condition_matches(self):
        rule = AutomationRule(conditions=[{"field": "priority", "op": "eq", "value": "high"}])
        self.assertTrue(rule_matches(rule, self.ticket))

    def test_eq_condition_no_match(self):
        rule = AutomationRule(conditions=[{"field": "priority", "op": "eq", "value": "low"}])
        self.assertFalse(rule_matches(rule, self.ticket))

    def test_contains_condition(self):
        rule = AutomationRule(conditions=[{"field": "title", "op": "contains", "value": "vpn"}])
        self.assertTrue(rule_matches(rule, self.ticket))

    def test_empty_conditions_always_match(self):
        self.assertTrue(rule_matches(AutomationRule(conditions=[]), self.ticket))

    def test_all_conditions_required(self):
        rule = AutomationRule(
            conditions=[
                {"field": "priority", "op": "eq", "value": "high"},
                {"field": "status", "op": "eq", "value": "closed"},
            ]
        )
        self.assertFalse(rule_matches(rule, self.ticket))


class ApplyActionsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", "u@x.com", "p")
        self.agent = User.objects.create_user("a", "a@x.com", "p", role="agent")
        self.ticket = Ticket.objects.create(
            title="T", description="d", created_by=self.user, priority="low", tags=""
        )

    def test_set_priority_and_tag(self):
        rule = AutomationRule(
            actions=[
                {"type": "set_priority", "value": "critical"},
                {"type": "add_tag", "value": "escalated"},
            ]
        )
        applied = apply_actions(rule, self.ticket)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, "critical")
        self.assertIn("escalated", self.ticket.tags)
        self.assertEqual(set(applied), {"set_priority", "add_tag"})

    def test_assign_action(self):
        rule = AutomationRule(actions=[{"type": "assign", "value": self.agent.pk}])
        apply_actions(rule, self.ticket)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.agent)

    def test_add_note_records_system_event(self):
        rule = AutomationRule(actions=[{"type": "add_note", "value": "auto note"}])
        apply_actions(rule, self.ticket)
        self.assertTrue(TicketMessage.objects.filter(ticket=self.ticket, kind="system").exists())

    def test_invalid_action_ignored(self):
        rule = AutomationRule(actions=[{"type": "nonsense", "value": "x"}, "notadict"])
        self.assertEqual(apply_actions(rule, self.ticket), [])


class RunRulesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", "u@x.com", "p")

    def test_on_create_rule_runs_via_signal(self):
        AutomationRule.objects.create(
            name="Escalate VPN",
            trigger="on_create",
            conditions=[{"field": "title", "op": "contains", "value": "vpn"}],
            actions=[{"type": "set_priority", "value": "critical"}],
        )
        ticket = Ticket.objects.create(
            title="VPN outage", description="d", created_by=self.user, priority="low"
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.priority, "critical")

    def test_run_rules_increments_run_count(self):
        rule = AutomationRule.objects.create(
            name="R", trigger="on_reply", actions=[{"type": "add_tag", "value": "x"}]
        )
        ticket = Ticket.objects.create(title="T", description="d", created_by=self.user)
        run_rules(ticket, "on_reply")
        rule.refresh_from_db()
        self.assertEqual(rule.run_count, 1)

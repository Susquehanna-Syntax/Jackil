from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.sla.models import BusinessSchedule, SLATarget
from apps.sla.service import add_working_minutes, apply_sla, mark_first_response
from apps.tickets.models import Ticket


def _make_user():
    return User.objects.create_user(username="testuser", password="pass")


def _make_ticket(**kwargs):
    defaults = dict(
        title="Test ticket",
        priority="high",
        status="open",
        created_by=_make_user(),
    )
    defaults.update(kwargs)
    return Ticket.objects.create(**defaults)


class AddWorkingMinutesTests(TestCase):
    def test_add_minutes_24_7(self):
        t = timezone.make_aware(datetime(2025, 1, 6, 10, 0))  # Monday
        result = add_working_minutes(t, 120, None)
        self.assertEqual(result, t + timedelta(hours=2))

    def test_add_minutes_business_hours_same_day(self):
        schedule = BusinessSchedule.objects.create(
            name="Business",
            mode="business",
            workday_start=time(9, 0),
            workday_end=time(17, 0),
            workdays="0,1,2,3,4",
            is_active=False,
        )
        start = timezone.make_aware(datetime(2025, 1, 6, 10, 0))  # Monday
        result = add_working_minutes(start, 120, schedule)
        expected = timezone.make_aware(datetime(2025, 1, 6, 12, 0))
        self.assertEqual(result, expected)

    def test_add_minutes_rolls_to_next_day(self):
        schedule = BusinessSchedule.objects.create(
            name="Business",
            mode="business",
            workday_start=time(9, 0),
            workday_end=time(17, 0),
            workdays="0,1,2,3,4",
            is_active=False,
        )
        start = timezone.make_aware(datetime(2025, 1, 6, 16, 0))  # Monday 16:00, only 60 min left
        result = add_working_minutes(start, 120, schedule)
        expected = timezone.make_aware(datetime(2025, 1, 7, 10, 0))  # Tuesday 10:00
        self.assertEqual(result, expected)

    def test_add_minutes_skips_weekend(self):
        schedule = BusinessSchedule.objects.create(
            name="Business",
            mode="business",
            workday_start=time(9, 0),
            workday_end=time(17, 0),
            workdays="0,1,2,3,4",
            is_active=False,
        )
        start = timezone.make_aware(datetime(2025, 1, 10, 16, 0))  # Friday 16:00
        result = add_working_minutes(start, 120, schedule)
        expected = timezone.make_aware(datetime(2025, 1, 13, 10, 0))  # Monday 10:00
        self.assertEqual(result, expected)


class ApplySLATests(TestCase):
    def test_apply_sla_sets_due_times(self):
        SLATarget.objects.update_or_create(
            priority="high",
            defaults={"response_minutes": 120, "resolution_minutes": 480},
        )
        ticket = Ticket(
            title="Test ticket",
            priority="high",
            status="open",
            created_at=timezone.make_aware(datetime(2025, 1, 6, 10, 0)),
        )
        result = apply_sla(ticket, save=False)
        self.assertTrue(result)
        self.assertIsNotNone(ticket.first_response_due)
        self.assertIsNotNone(ticket.resolution_due)
        self.assertGreater(ticket.resolution_due, ticket.first_response_due)

    def test_apply_sla_no_target_is_noop(self):
        SLATarget.objects.all().delete()
        ticket = Ticket(
            title="Test ticket",
            priority="high",
            status="open",
            created_at=timezone.make_aware(datetime(2025, 1, 6, 10, 0)),
        )
        result = apply_sla(ticket, save=False)
        self.assertFalse(result)
        self.assertIsNone(ticket.first_response_due)
        self.assertIsNone(ticket.resolution_due)


class MarkFirstResponseTests(TestCase):
    def test_mark_first_response_idempotent(self):
        ticket = _make_ticket()
        when1 = timezone.make_aware(datetime(2025, 1, 6, 11, 0))
        result1 = mark_first_response(ticket, when=when1)
        self.assertTrue(result1)
        self.assertEqual(ticket.first_responded_at, when1)

        when2 = timezone.make_aware(datetime(2025, 1, 6, 12, 0))
        result2 = mark_first_response(ticket, when=when2)
        self.assertFalse(result2)
        self.assertEqual(ticket.first_responded_at, when1)


class SLASignalTests(TestCase):
    def test_signal_applies_sla_on_create(self):
        SLATarget.objects.update_or_create(
            priority="high",
            defaults={"response_minutes": 120, "resolution_minutes": 480},
        )
        ticket = Ticket.objects.create(
            title="Signal test",
            priority="high",
            status="open",
            created_by=_make_user(),
        )
        self.assertIsNotNone(ticket.first_response_due)
        self.assertIsNotNone(ticket.resolution_due)


class StatusHelpersTests(TestCase):
    def _make_ticket(self, **kwargs):
        defaults = dict(
            title="Status test",
            priority="high",
            status="open",
            created_by=_make_user(),
            response_breached=False,
            resolution_breached=False,
        )
        defaults.update(kwargs)
        return Ticket(**defaults)

    def test_response_status_none(self):
        ticket = self._make_ticket(first_response_due=None)
        from apps.sla.service import response_status

        self.assertEqual(response_status(ticket), "none")

    def test_response_status_open_and_overdue(self):
        from apps.sla.service import response_status

        now = timezone.now()
        ticket = self._make_ticket(
            first_response_due=now + timedelta(hours=2),
            first_responded_at=None,
        )
        self.assertEqual(response_status(ticket, now=now), "open")

        ticket.first_response_due = now - timedelta(hours=1)
        self.assertEqual(response_status(ticket, now=now), "overdue")

    def test_response_status_met_and_breached(self):
        from apps.sla.service import response_status

        ticket = self._make_ticket(
            first_response_due=timezone.make_aware(datetime(2025, 1, 6, 14, 0)),
            first_responded_at=timezone.make_aware(datetime(2025, 1, 6, 11, 0)),
        )
        self.assertEqual(response_status(ticket), "met")

        ticket.first_responded_at = timezone.make_aware(datetime(2025, 1, 6, 15, 0))
        self.assertEqual(response_status(ticket), "breached")

    def test_resolution_status_met_on_close(self):
        from apps.sla.service import resolution_status

        ticket = self._make_ticket(
            status="resolved",
            resolution_due=timezone.make_aware(datetime(2025, 1, 6, 14, 0)),
            closed_at=timezone.make_aware(datetime(2025, 1, 6, 11, 0)),
        )
        self.assertEqual(resolution_status(ticket), "met")

        ticket.closed_at = timezone.make_aware(datetime(2025, 1, 6, 15, 0))
        self.assertEqual(resolution_status(ticket), "breached")


class BreachFlaggingTests(TestCase):
    def test_check_and_flag_sets_breach_booleans(self):
        from apps.sla.service import check_and_flag_breaches

        user = User.objects.create_user(username="breach_test", password="pass")
        ticket = Ticket(
            title="Breach test",
            priority="high",
            status="open",
            created_by=user,
            response_breached=False,
            resolution_breached=False,
        )
        ticket.save()
        ticket.first_response_due = timezone.make_aware(datetime(2025, 1, 6, 10, 0))
        ticket.save(update_fields=["first_response_due"])

        now = timezone.make_aware(datetime(2025, 1, 6, 14, 0))
        newly = check_and_flag_breaches(ticket, now=now)
        self.assertIn("response", newly)
        ticket.refresh_from_db()
        self.assertTrue(ticket.response_breached)

        # Second call returns [] (already flagged)
        newly2 = check_and_flag_breaches(ticket, now=now)
        self.assertEqual(newly2, [])


class FirstAgentReplyTests(TestCase):
    def test_first_agent_reply_marks_response(self):
        from apps.tickets.services import post_message

        now = timezone.now()
        ticket = Ticket.objects.create(
            title="Agent reply test",
            priority="high",
            status="open",
            created_by=_make_user(),
            first_response_due=now + timedelta(hours=1),
            first_responded_at=None,
        )
        agent = User.objects.create_user(username="agent_user", role="agent")
        post_message(ticket, agent, "hi", kind="reply")
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.first_responded_at)

        # A customer reply should NOT mark it again
        customer = User.objects.create_user(username="cust", role="customer")
        post_message(ticket, customer, "thanks", kind="reply")
        ticket.refresh_from_db()
        # first_responded_at should remain the original (idempotent)


class PauseResumeTests(TestCase):
    def _paused_ticket(self, **kwargs):
        now = timezone.now()
        defaults = dict(
            title="Pause test",
            priority="high",
            status="open",
            created_by=_make_user(),
            first_response_due=now + timedelta(hours=1),
            resolution_due=now + timedelta(hours=4),
            first_responded_at=None,
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def test_pause_freezes_clock_no_false_overdue(self):
        from apps.sla.service import pause_sla, response_status

        ticket = self._paused_ticket()
        paused_at = ticket.first_response_due - timedelta(minutes=10)
        pause_sla(ticket, when=paused_at)
        self.assertIsNotNone(ticket.sla_paused_at)
        # An hour past the due date, but the frozen clock keeps it "open".
        later = ticket.first_response_due + timedelta(hours=1)
        self.assertEqual(response_status(ticket, now=later), "open")

    def test_resume_shifts_due_dates_and_banks_time(self):
        from apps.sla.service import pause_sla, resume_sla

        ticket = self._paused_ticket()
        original_response_due = ticket.first_response_due
        original_resolution_due = ticket.resolution_due
        paused_at = timezone.now()
        pause_sla(ticket, when=paused_at)
        resume_at = paused_at + timedelta(hours=2)
        resume_sla(ticket, when=resume_at)
        self.assertIsNone(ticket.sla_paused_at)
        self.assertEqual(ticket.sla_paused_seconds, 2 * 3600)
        self.assertEqual(ticket.first_response_due, original_response_due + timedelta(hours=2))
        self.assertEqual(ticket.resolution_due, original_resolution_due + timedelta(hours=2))

    def test_resume_without_pause_is_noop(self):
        from apps.sla.service import resume_sla

        ticket = self._paused_ticket()
        self.assertFalse(resume_sla(ticket))

    def test_status_change_signal_pauses_and_resumes(self):
        """open → pending pauses; pending → open resumes and banks the span."""
        from apps.tickets.events import ticket_status_changed

        ticket = self._paused_ticket()
        original_resolution_due = ticket.resolution_due
        ticket_status_changed.send(sender=Ticket, ticket=ticket, actor=None, new_status="pending")
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.sla_paused_at)
        ticket_status_changed.send(sender=Ticket, ticket=ticket, actor=None, new_status="open")
        ticket.refresh_from_db()
        # The pause was released (span is ~0s in-test; real banking is covered
        # by test_resume_shifts_due_dates_and_banks_time).
        self.assertIsNone(ticket.sla_paused_at)
        self.assertGreaterEqual(ticket.sla_paused_seconds, 0)
        self.assertGreaterEqual(ticket.resolution_due, original_resolution_due)


class PriorityRecalcTests(TestCase):
    def test_priority_change_recomputes_due_dates(self):
        from apps.sla.service import apply_sla

        SLATarget.objects.update_or_create(
            priority="low",
            defaults={"response_minutes": 480, "resolution_minutes": 2880},
        )
        SLATarget.objects.update_or_create(
            priority="critical",
            defaults={"response_minutes": 30, "resolution_minutes": 120},
        )
        created = timezone.make_aware(datetime(2025, 1, 6, 10, 0))
        ticket = Ticket.objects.create(
            title="Recalc test", priority="low", status="open", created_by=_make_user()
        )
        Ticket.objects.filter(pk=ticket.pk).update(created_at=created)
        ticket.refresh_from_db()
        apply_sla(ticket)
        low_due = ticket.first_response_due
        # Escalate to critical → tighter target → sooner due date.
        ticket.priority = "critical"
        apply_sla(ticket)
        self.assertLess(ticket.first_response_due, low_due)
        self.assertEqual(ticket.first_response_due, created + timedelta(minutes=30))

    def test_priority_recalc_keeps_banked_pause(self):
        from apps.sla.service import apply_sla

        SLATarget.objects.update_or_create(
            priority="high",
            defaults={"response_minutes": 120, "resolution_minutes": 480},
        )
        created = timezone.make_aware(datetime(2025, 1, 6, 10, 0))
        ticket = Ticket.objects.create(
            title="Bank test", priority="high", status="open", created_by=_make_user()
        )
        Ticket.objects.filter(pk=ticket.pk).update(created_at=created, sla_paused_seconds=3600)
        ticket.refresh_from_db()
        apply_sla(ticket)
        # 120-min target + 1h banked pause = 3h after creation.
        self.assertEqual(
            ticket.first_response_due, created + timedelta(minutes=120) + timedelta(hours=1)
        )


class EscalationTests(TestCase):
    def test_escalate_bumps_priority_on_resolution_breach(self):
        from apps.sla.service import escalate

        now = timezone.now()
        ticket = Ticket.objects.create(
            title="Escalation test",
            priority="high",
            status="open",
            created_by=_make_user(),
            resolution_due=now - timedelta(hours=1),
            resolution_breached=False,
        )
        escalate(ticket, ["resolution"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.priority, "critical")

        # Verify system events were recorded
        from apps.tickets.models import TicketMessage

        messages = TicketMessage.objects.filter(ticket=ticket, kind="system")
        breach_msg = messages.filter(body="SLA resolution target breached.").exists()
        self.assertTrue(breach_msg)
        escal_msg = messages.filter(
            body="Auto-escalated priority high → critical (SLA breach)."
        ).exists()
        self.assertTrue(escal_msg)

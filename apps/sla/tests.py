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

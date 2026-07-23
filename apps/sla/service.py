from datetime import timedelta

from django.utils import timezone

from .models import BusinessSchedule, SLATarget


def add_working_minutes(start, minutes, schedule):
    """Return the datetime `minutes` working-minutes after `start`.

    With no schedule or a 24/7 schedule, this is plain elapsed time. With a
    business-hours schedule, only minutes inside workday windows on workdays
    count."""
    if schedule is None or schedule.mode == "24_7":
        return start + timedelta(minutes=minutes)
    workdays = schedule.workday_set()
    remaining = float(minutes)
    cursor = start
    guard = 0
    while remaining > 0 and guard < 100000:
        guard += 1
        day_start = cursor.replace(
            hour=schedule.workday_start.hour,
            minute=schedule.workday_start.minute,
            second=0,
            microsecond=0,
        )
        day_end = cursor.replace(
            hour=schedule.workday_end.hour,
            minute=schedule.workday_end.minute,
            second=0,
            microsecond=0,
        )
        if cursor.weekday() not in workdays or cursor >= day_end:
            cursor = (cursor + timedelta(days=1)).replace(
                hour=schedule.workday_start.hour,
                minute=schedule.workday_start.minute,
                second=0,
                microsecond=0,
            )
            continue
        if cursor < day_start:
            cursor = day_start
        avail = (day_end - cursor).total_seconds() / 60.0
        if remaining <= avail:
            return cursor + timedelta(minutes=remaining)
        remaining -= avail
        cursor = (cursor + timedelta(days=1)).replace(
            hour=schedule.workday_start.hour,
            minute=schedule.workday_start.minute,
            second=0,
            microsecond=0,
        )
    return cursor


# Ticket statuses during which the SLA clock is frozen.
PAUSED_STATUSES = {"pending"}


def applicable_target(ticket):
    return SLATarget.objects.filter(active=True, priority=ticket.priority).first()


def apply_sla(ticket, save=True):
    """Compute and set first_response_due / resolution_due from the ticket's
    priority target. No-op if there is no matching target.

    Any time already banked in ``sla_paused_seconds`` is added back so that a
    priority change recomputes the targets without discarding earned pause
    credit. Called on ticket creation and on every priority change."""
    target = applicable_target(ticket)
    if target is None:
        return False
    schedule = BusinessSchedule.active()
    base = ticket.created_at or timezone.now()
    paused = timedelta(seconds=ticket.sla_paused_seconds or 0)
    ticket.first_response_due = (
        add_working_minutes(base, target.response_minutes, schedule) + paused
    )
    ticket.resolution_due = add_working_minutes(base, target.resolution_minutes, schedule) + paused
    if save:
        ticket.save(update_fields=["first_response_due", "resolution_due"])
    return True


def _effective_now(ticket, now):
    """The clock reading to judge an open target against. While the ticket is
    paused it is frozen at the instant the pause began, so a ticket sitting in
    Pending never drifts into 'overdue'."""
    if ticket.sla_paused_at is not None:
        return min(now, ticket.sla_paused_at)
    return now


def pause_sla(ticket, when=None):
    """Freeze the SLA clock (called when a ticket enters a paused status).
    Idempotent and a no-op when the ticket has no SLA targets."""
    if ticket.sla_paused_at is not None:
        return False
    if ticket.first_response_due is None and ticket.resolution_due is None:
        return False
    ticket.sla_paused_at = when or timezone.now()
    ticket.save(update_fields=["sla_paused_at"])
    return True


def resume_sla(ticket, when=None):
    """Resume a paused clock: push the still-open due dates forward by however
    long the ticket was paused, and bank that time in sla_paused_seconds."""
    if ticket.sla_paused_at is None:
        return False
    now = when or timezone.now()
    delta = now - ticket.sla_paused_at
    if delta.total_seconds() < 0:
        delta = timedelta(0)
    if ticket.first_response_due is not None and ticket.first_responded_at is None:
        ticket.first_response_due += delta
    if ticket.resolution_due is not None and ticket.status not in ("resolved", "closed"):
        ticket.resolution_due += delta
    ticket.sla_paused_seconds = (ticket.sla_paused_seconds or 0) + int(delta.total_seconds())
    ticket.sla_paused_at = None
    ticket.save(
        update_fields=[
            "first_response_due",
            "resolution_due",
            "sla_paused_seconds",
            "sla_paused_at",
        ]
    )
    return True


def mark_first_response(ticket, when=None):
    """Record the first agent response time (idempotent)."""
    if ticket.first_responded_at is None:
        ticket.first_responded_at = when or timezone.now()
        ticket.save(update_fields=["first_responded_at"])
        return True
    return False


def response_status(ticket, now=None):
    """'none' | 'open' | 'overdue' | 'met' | 'breached'."""
    if ticket.first_response_due is None:
        return "none"
    if ticket.first_responded_at is not None:
        return "met" if ticket.first_responded_at <= ticket.first_response_due else "breached"
    now = _effective_now(ticket, now or timezone.now())
    return "overdue" if now > ticket.first_response_due else "open"


def resolution_status(ticket, now=None):
    if ticket.resolution_due is None:
        return "none"
    if ticket.status in ("resolved", "closed") and ticket.closed_at is not None:
        return "met" if ticket.closed_at <= ticket.resolution_due else "breached"
    now = _effective_now(ticket, now or timezone.now())
    return "overdue" if now > ticket.resolution_due else "open"


def check_and_flag_breaches(ticket, now=None):
    """Update the breach booleans from current status; return the list of
    kinds ('response'/'resolution') that are newly breached this call."""
    now = now or timezone.now()
    newly = []
    r = response_status(ticket, now)
    if r in ("overdue", "breached") and not ticket.response_breached:
        ticket.response_breached = True
        newly.append("response")
    res = resolution_status(ticket, now)
    if res in ("overdue", "breached") and not ticket.resolution_breached:
        ticket.resolution_breached = True
        newly.append("resolution")
    if newly:
        ticket.save(update_fields=["response_breached", "resolution_breached"])
    return newly


def escalate(ticket, kinds):
    """Record a system event for each newly-breached SLA kind. On a resolution
    breach, bump priority one level (low→medium→high→critical)."""
    from apps.tickets.services import record_system_event

    order = ["low", "medium", "high", "critical"]
    for kind in kinds:
        record_system_event(ticket, None, f"SLA {kind} target breached.")
    if "resolution" in kinds and ticket.priority in order and ticket.priority != "critical":
        new_priority = order[order.index(ticket.priority) + 1]
        record_system_event(
            ticket,
            None,
            f"Auto-escalated priority {ticket.priority} → {new_priority} (SLA breach).",
        )
        ticket.priority = new_priority
        ticket.save(update_fields=["priority"])

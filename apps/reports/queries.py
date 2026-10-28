"""Pure report queries over a ticket queryset and a date window.

Every function takes a ticket queryset (already narrowed to the report's
sources) and returns either ``(labels, series)`` for the days family —
labels the ISO dates in the window, series a list of ``(name, values)`` —
or ``rows``, a list of ``(label, number)``, for the rows family.
"""

import statistics
from datetime import timedelta

from django.utils import timezone

from apps.sla.service import resolution_status
from apps.tickets.models import Ticket, TicketRating

RESOLVED_STATUSES = ("resolved", "closed")
OPEN_STATUSES = tuple(value for value, _ in Ticket.STATUS_CHOICES if value not in RESOLVED_STATUSES)


def _day(dt):
    return timezone.localdate(dt).isoformat() if dt is not None else None


def _days(start, end):
    labels = []
    day = start
    while day <= end:
        labels.append(day.isoformat())
        day += timedelta(days=1)
    return labels


def _group_by_day(tickets, when):
    """{ISO date: [ticket, ...]} keyed on the local date of *when*."""
    buckets = {}
    for ticket in tickets:
        label = _day(when(ticket))
        if label is not None:
            buckets.setdefault(label, []).append(ticket)
    return buckets


def _median_hours(pairs):
    """Median hours from created_at to *until*, or 0 with no data."""
    hours = [
        (until - created).total_seconds() / 3600 for created, until in pairs if until is not None
    ]
    if not hours:
        return 0
    return round(statistics.median(hours), 1)


def ticket_volume(tickets, start, end):
    """Tickets created per day, and resolved/closed per day by closed_at."""
    labels = _days(start, end)
    created = _group_by_day(tickets, lambda t: t.created_at)
    resolved = _group_by_day(tickets.filter(status__in=RESOLVED_STATUSES), lambda t: t.closed_at)
    series = [
        ("Created", [len(created.get(label, [])) for label in labels]),
        ("Resolved", [len(resolved.get(label, [])) for label in labels]),
    ]
    return labels, series


def sla_compliance(tickets, start, end):
    """Share of per-day closures that met their resolution due date."""
    labels = _days(start, end)
    closed = _group_by_day(tickets.filter(status__in=RESOLVED_STATUSES), lambda t: t.closed_at)
    values = []
    for label in labels:
        day_tickets = [t for t in closed.get(label, []) if t.resolution_due is not None]
        total = 0
        met = 0
        for ticket in day_tickets:
            status = resolution_status(ticket)
            if status in ("met", "breached"):
                total += 1
                if status == "met":
                    met += 1
        values.append(round(met * 100 / total, 1) if total else 0)
    return labels, [("Within SLA (%)", values)]


def first_response_time(tickets, start, end):
    """Median hours from creation to first response, per day of creation."""
    labels = _days(start, end)
    created = _group_by_day(tickets, lambda t: t.created_at)
    values = [
        _median_hours([(t.created_at, t.first_responded_at) for t in created.get(label, [])])
        for label in labels
    ]
    return labels, [("Hours", values)]


def resolution_time(tickets, start, end):
    """Median hours from creation to closure, per day of closure."""
    labels = _days(start, end)
    closed = _group_by_day(tickets.filter(status__in=RESOLVED_STATUSES), lambda t: t.closed_at)
    values = [
        _median_hours([(t.created_at, t.closed_at) for t in closed.get(label, [])])
        for label in labels
    ]
    return labels, [("Hours", values)]


def csat(tickets, start, end):
    """Mean CSAT score per day of the rating's creation."""
    labels = _days(start, end)
    buckets = {}
    for rating in TicketRating.objects.filter(ticket__in=tickets):
        label = _day(rating.created_at)
        if label is not None:
            buckets.setdefault(label, []).append(rating.score)
    values = []
    for label in labels:
        scores = buckets.get(label, [])
        values.append(round(sum(scores) / len(scores), 1) if scores else 0)
    return labels, [("Average score", values)]


def status_mix(tickets):
    """Ticket counts in STATUS_CHOICES order, zeros included."""
    counts = {value: 0 for value, _ in Ticket.STATUS_CHOICES}
    for ticket in tickets.values_list("status", flat=True):
        if ticket in counts:
            counts[ticket] += 1
    return [(label, counts[value]) for value, label in Ticket.STATUS_CHOICES]


def priority_mix(tickets):
    """Open-ticket counts in PRIORITY_CHOICES order, zeros included."""
    counts = {value: 0 for value, _ in Ticket.PRIORITY_CHOICES}
    for ticket in tickets.filter(status__in=OPEN_STATUSES).values_list("priority", flat=True):
        if ticket in counts:
            counts[ticket] += 1
    return [(label, counts[value]) for value, label in Ticket.PRIORITY_CHOICES]


def agent_load(tickets):
    """Open tickets assigned per agent/admin, most loaded first."""
    from apps.accounts.models import User

    loads = {}
    for user in User.objects.filter(role__in=("agent", "admin")):
        loads[user.pk] = [user.get_full_name() or user.username, 0]
    for pk in (
        tickets.filter(status__in=OPEN_STATUSES)
        .exclude(assigned_to__isnull=True)
        .values_list("assigned_to", flat=True)
    ):
        if pk in loads:
            loads[pk][1] += 1
    rows = [(name, count) for name, count in loads.values()]
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows

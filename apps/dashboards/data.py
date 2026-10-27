"""The data behind every Jackil widget, in its contract shape.

One function per registry kind, keyed in ``DATA``; ``widget_data`` is the
entry point the API view calls. Each returns the *inner* payload — the
envelope and its validation are the contract's job.
"""

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone

from apps.tickets.filters import filter_tickets
from apps.tickets.models import SavedView, Ticket

from .contract import envelope
from .widgets import WIDGET_REGISTRY, clean_settings

#: Statuses a ticket is still "live" in. Resolved and closed are out of the
#: operational counts.
OPEN = ("open", "in_progress", "pending")
RESOLVED = ("resolved", "closed")

#: How close to its resolution due time makes a ticket "needs attention".
ATTENTION_WINDOW = timedelta(hours=4)


def _open_tickets():
    return Ticket.objects.filter(status__in=OPEN)


def _ticket_item(ticket, meta, tone=None, badge=None):
    item = {
        "title": f"#{ticket.pk} {ticket.title}",
        "href": reverse("tickets:ticket_detail", args=[ticket.pk]),
        "meta": meta,
    }
    if tone is not None:
        item["tone"] = tone
    if badge is not None:
        item["badge"] = badge
    return item


_STAT_LABELS = {
    "open": "Open",
    "unassigned": "Unassigned",
    "overdue": "Overdue",
    "breached": "SLA breached",
    "critical": "Critical",
    "created_week": "Created this week",
    "resolved_week": "Resolved this week",
}

#: Stats where a non-zero number is itself the bad news.
_ALARM_STATS = ("overdue", "breached", "critical")


def stat_tile(settings, user):
    which = settings["stat"]
    now = timezone.now()
    qs = _open_tickets()
    if which == "unassigned":
        qs = qs.filter(assigned_to__isnull=True)
    elif which == "overdue":
        qs = qs.filter(resolution_due__lt=now)
    elif which == "breached":
        qs = qs.filter(resolution_breached=True)
    elif which == "critical":
        qs = qs.filter(priority="critical")
    elif which == "created_week":
        qs = Ticket.objects.filter(created_at__gte=now - timedelta(days=7))
    elif which == "resolved_week":
        qs = Ticket.objects.filter(status__in=RESOLVED, closed_at__gte=now - timedelta(days=7))

    value = qs.count()
    if which in _ALARM_STATS:
        tone = "bad" if value else "ok"
    else:
        tone = "info"

    href = reverse("tickets:ticket_list")
    extra = {"unassigned": "assigned=unassigned", "critical": "priority=critical"}.get(which)
    if extra:
        href = f"{href}?{extra}"

    return {"value": value, "label": _STAT_LABELS[which], "tone": tone, "href": href}


def needs_attention(settings, user):
    now = timezone.now()
    tickets = (
        _open_tickets()
        .filter(resolution_due__lte=now + ATTENTION_WINDOW)
        .order_by("resolution_due")[: settings["limit"]]
    )
    items = []
    for t in tickets:
        overdue = t.resolution_due is not None and t.resolution_due <= now
        items.append(
            _ticket_item(
                t,
                meta="Overdue" if overdue else "Due soon",
                tone="bad" if overdue else "warn",
                badge=t.get_priority_display(),
            )
        )
    return {"items": items, "empty": "Nothing is close to its due time."}


def my_work(settings, user):
    open_qs = _open_tickets()
    tickets = (open_qs.filter(assigned_to=user) | open_qs.filter(assigned_users=user)).distinct()
    items = [
        _ticket_item(t, meta=t.get_status_display())
        for t in tickets.order_by("-created_at")[: settings["limit"]]
    ]
    return {"items": items, "empty": "Nothing is assigned to you."}


_EMPTY_VIEW = "That saved view no longer exists, or is not shared with you."


def ticket_list(settings, user):
    limit = settings["limit"]
    if settings["saved_view"]:
        view = SavedView.objects.filter(
            Q(owner=user) | Q(is_shared=True), pk=settings["saved_view"]
        ).first()
        if view is None:
            return {"items": [], "empty": _EMPTY_VIEW}
        qs = filter_tickets(Ticket.objects.all(), QueryDict(view.query), user)
    else:
        qs = _open_tickets()

    items = [
        _ticket_item(t, meta=t.get_status_display(), badge=t.get_priority_display())
        for t in qs.order_by("-created_at")[:limit]
    ]
    return {"items": items, "empty": "No tickets match."}


def sla_compliance(settings, user):
    now = timezone.now()
    since = now - timedelta(days=settings["range_days"])
    resolved = Ticket.objects.filter(status__in=RESOLVED, closed_at__gte=since).exclude(
        resolution_due=None
    )
    total = resolved.count()
    if total == 0:
        return {
            "value": None,
            "label": "Resolved within SLA",
            "sub": f"No resolved tickets with an SLA in the last {settings['range_days']} days",
        }
    within = resolved.filter(resolution_breached=False).count()
    value = round(within * 100 / total, 1)
    if value >= 90:
        tone = "ok"
    elif value >= 75:
        tone = "warn"
    else:
        tone = "bad"
    return {
        "value": value,
        "label": "Resolved within SLA",
        "tone": tone,
        "sub": f"{total} tickets, last {settings['range_days']} days",
    }


def _counts_by_choice(qs, field: str, choices) -> list[int]:
    """Count *qs* per choice value, in ``choices`` order, zeros included."""
    counts = dict(qs.values_list(field).annotate(n=Count("pk")))
    return [counts.get(value, 0) for value, _label in choices]


def tickets_by_status(settings, user):
    labels = [label for _value, label in Ticket.STATUS_CHOICES]
    values = _counts_by_choice(Ticket.objects.all(), "status", Ticket.STATUS_CHOICES)
    return {"kind": "bar", "labels": labels, "series": [{"name": "Tickets", "values": values}]}


def tickets_by_priority(settings, user):
    labels = [label for _value, label in Ticket.PRIORITY_CHOICES]
    values = _counts_by_choice(_open_tickets(), "priority", Ticket.PRIORITY_CHOICES)
    return {"kind": "bar", "labels": labels, "series": [{"name": "Tickets", "values": values}]}


def volume_trend(settings, user):
    today = timezone.localdate()
    days = [today - timedelta(days=offset) for offset in range(settings["range_days"] - 1, -1, -1)]

    # The window is the local calendar range; datetimes are filtered against
    # its UTC instant (USE_TZ is on), not a naive date string.
    since = timezone.make_aware(datetime.combine(days[0], time.min))

    def per_day(qs, date_field):
        rows = qs.annotate(day=TruncDate(date_field)).values("day").annotate(n=Count("pk"))
        counts = {row["day"]: row["n"] for row in rows}
        return [counts.get(d, 0) for d in days]

    created = per_day(Ticket.objects.filter(created_at__gte=since), "created_at")
    resolved = per_day(
        Ticket.objects.filter(status__in=RESOLVED, closed_at__gte=since), "closed_at"
    )
    return {
        "kind": "line",
        "labels": [d.isoformat() for d in days],
        "series": [
            {"name": "Created", "values": created},
            {"name": "Resolved", "values": resolved},
        ],
    }


def agent_load(settings, user):
    User = get_user_model()
    agents = User.objects.filter(role__in=("agent", "admin"))
    rows = []
    for agent in agents:
        name = agent.get_full_name() or agent.username
        assigned = _open_tickets().filter(assigned_to=agent)
        rows.append([name, assigned.count(), assigned.filter(priority="critical").count()])
    rows.sort(key=lambda row: (-row[1], row[0]))
    return {"columns": ["Agent", "Open", "Critical"], "rows": rows}


DATA = {
    "stat_tile": stat_tile,
    "ticket_list": ticket_list,
    "needs_attention": needs_attention,
    "my_work": my_work,
    "sla_compliance": sla_compliance,
    "tickets_by_status": tickets_by_status,
    "tickets_by_priority": tickets_by_priority,
    "volume_trend": volume_trend,
    "agent_load": agent_load,
}


def widget_data(kind: str, raw_settings, user) -> dict:
    """The versioned envelope for one widget. ``KeyError`` on unknown kind."""
    settings = clean_settings(kind, raw_settings)
    data = DATA[kind](settings, user)
    return envelope(WIDGET_REGISTRY[kind]["shape"], data)

"""Pure report queries over a source queryset and a date window.

Every function takes the report's source — a ticket queryset for ticket
kinds, a project queryset for project kinds, ``None`` for wiki kinds — and
returns either ``(labels, series)`` for the days and groups families —
labels plus series, each a ``(name, values)`` pair — or ``rows``, a list of
``(label, number)``, for the rows family.
"""

import statistics
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.projects import metrics
from apps.projects.cost import total_cost
from apps.projects.models import Issue, Project, Sprint
from apps.projects.permissions import staff_users
from apps.projects.views import display_name
from apps.sla.service import resolution_status
from apps.tickets.models import Ticket, TicketRating
from apps.wiki.models import Page, PageVersion

RESOLVED_STATUSES = ("resolved", "closed")
OPEN_STATUSES = tuple(value for value, _ in Ticket.STATUS_CHOICES if value not in RESOLVED_STATUSES)
#: Done issues with one of these types carry a price; epics and sub-tasks don't.
PRICED_TYPES = ("story", "task", "bug")
#: The cost cards show twelve sprints at most.
MAX_SPRINTS = 12


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


def _created_in(tickets, start, end):
    """Only the tickets created inside the window: the rest cannot land on a label."""
    return tickets.filter(created_at__date__range=(start, end))


def _counts_per_day(rows, field, start, end, labels):
    """Zero-filled daily counts over the window, one entry per label.

    Bucketed from each row's local date rather than a SQL day truncation:
    SQLite's ``date()`` reads the stored UTC instant, so a truncated key can
    sit a day away from the row the ``__date`` lookup just matched. The ticket
    queries group in Python for the same reason.
    """
    by_label = dict.fromkeys(labels, 0)
    for instant in rows.filter(**{f"{field}__date__range": (start, end)}).values_list(
        field, flat=True
    ):
        key = _day(instant)
        if key is not None:
            by_label[key] += 1
    return [by_label[label] for label in labels]


def _closed_in(tickets, start, end):
    return tickets.filter(status__in=RESOLVED_STATUSES, closed_at__date__range=(start, end))


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
    created = _group_by_day(_created_in(tickets, start, end), lambda t: t.created_at)
    resolved = _group_by_day(_closed_in(tickets, start, end), lambda t: t.closed_at)
    series = [
        ("Created", [len(created.get(label, [])) for label in labels]),
        ("Resolved", [len(resolved.get(label, [])) for label in labels]),
    ]
    return labels, series


def sla_compliance(tickets, start, end):
    """Share of per-day closures that met their resolution due date."""
    labels = _days(start, end)
    closed = _group_by_day(_closed_in(tickets, start, end), lambda t: t.closed_at)
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
    created = _group_by_day(_created_in(tickets, start, end), lambda t: t.created_at)
    values = [
        _median_hours([(t.created_at, t.first_responded_at) for t in created.get(label, [])])
        for label in labels
    ]
    return labels, [("Hours", values)]


def resolution_time(tickets, start, end):
    """Median hours from creation to closure, per day of closure."""
    labels = _days(start, end)
    closed = _group_by_day(_closed_in(tickets, start, end), lambda t: t.closed_at)
    values = [
        _median_hours([(t.created_at, t.closed_at) for t in closed.get(label, [])])
        for label in labels
    ]
    return labels, [("Hours", values)]


def csat(tickets, start, end):
    """Mean CSAT score per day of the rating's creation."""
    labels = _days(start, end)
    buckets = {}
    for rating in TicketRating.objects.filter(
        ticket__in=tickets, created_at__date__range=(start, end)
    ):
        label = _day(rating.created_at)
        if label is not None:
            buckets.setdefault(label, []).append(rating.score)
    values = []
    for label in labels:
        scores = buckets.get(label, [])
        values.append(round(sum(scores) / len(scores), 1) if scores else 0)
    return labels, [("Average score", values)]


def status_mix(tickets, start=None, end=None):
    """Ticket counts in STATUS_CHOICES order, zeros included."""
    counts = {value: 0 for value, _ in Ticket.STATUS_CHOICES}
    for ticket in tickets.values_list("status", flat=True):
        if ticket in counts:
            counts[ticket] += 1
    return [(label, counts[value]) for value, label in Ticket.STATUS_CHOICES]


def priority_mix(tickets, start=None, end=None):
    """Open-ticket counts in PRIORITY_CHOICES order, zeros included."""
    counts = {value: 0 for value, _ in Ticket.PRIORITY_CHOICES}
    for ticket in tickets.filter(status__in=OPEN_STATUSES).values_list("priority", flat=True):
        if ticket in counts:
            counts[ticket] += 1
    return [(label, counts[value]) for value, label in Ticket.PRIORITY_CHOICES]


def agent_load(tickets, start=None, end=None):
    """Open tickets assigned per agent/admin, most loaded first."""
    loads = {}
    for user in staff_users():
        loads[user.pk] = [display_name(user), 0]
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


def _cents(amount):
    """The contract wants numbers; money is Decimal until this one line."""
    return float(amount.quantize(Decimal("0.01")))


def _done_issues(projects, sprint=None):
    """Finished issues of *projects* that carry a price — never epics or sub-tasks."""
    issues = Issue.objects.filter(project__in=projects, column__category="done").filter(
        type__in=PRICED_TYPES
    )
    if sprint is not None:
        issues = issues.filter(sprint=sprint)
    return issues


def velocity(projects, start=None, end=None):
    """Committed against completed points per closed sprint, first project only."""
    project = projects.order_by("key").first()
    if project is None:
        return [], [("Committed", []), ("Completed", [])]
    chart = metrics.velocity_chart(project)
    return chart["labels"], [(s["name"], s["values"]) for s in chart["series"]]


def burndown(projects, start=None, end=None):
    """The first project's active sprint burndown."""
    project = projects.order_by("key").first()
    sprint = None if project is None else project.sprints.filter(state="active").first()
    if sprint is None:
        return [], [("Remaining", []), ("Ideal", [])]
    chart = metrics.burndown(sprint)
    return chart["labels"], [(s["name"], s["values"]) for s in chart["series"]]


def cost_by_project(projects, start=None, end=None):
    """Rows of (project key, money spent on finished work), in key order."""
    rows = []
    for project in projects.order_by("key"):
        total, _left_out = total_cost(_done_issues(Project.objects.filter(pk=project.pk)))
        rows.append((project.key, _cents(total)))
    return rows


def cost_by_sprint(projects, start=None, end=None):
    """Rows of (sprint label, money spent), oldest closed sprint first."""
    closed = list(
        Sprint.objects.filter(project__in=projects, state="closed", closed_at__isnull=False)
        .select_related("project")
        .order_by("closed_at", "id")
    )
    rows = []
    for sprint in closed[-MAX_SPRINTS:]:
        total, _left_out = total_cost(_done_issues(projects, sprint=sprint))
        rows.append((f"{sprint.project.key} {sprint.name}", _cents(total)))
    return rows


def cost_per_point(projects, start=None, end=None):
    """Rows of (person, money per story point), dearest first."""
    points = {}
    spent = {}
    order = []
    for issue in _done_issues(projects).select_related("completed_by", "assignee"):
        person = issue.completed_by or issue.assignee
        if person is None:
            continue
        total, _left_out = total_cost([issue])
        if person.pk not in points:
            points[person.pk] = 0
            spent[person.pk] = Decimal("0")
            order.append(person)
        points[person.pk] += issue.story_points or 0
        spent[person.pk] += total
    rows = [
        (display_name(person), _cents(spent[person.pk] / Decimal(points[person.pk])))
        for person in order
        if points[person.pk] > 0
    ]
    rows.sort(key=lambda row: -row[1])
    return rows


def wiki_activity(source, start, end):
    """Pages created and pages edited per day inside the report's window."""
    labels = _days(start, end)
    return labels, [
        ("Created", _counts_per_day(Page.objects.all(), "created_at", start, end, labels)),
        (
            "Edited",
            _counts_per_day(
                PageVersion.objects.filter(number__gt=1), "created_at", start, end, labels
            ),
        ),
    ]


def wiki_top_pages(source, start=None, end=None):
    """Rows of (page title, views) for the ten most-read pages."""
    return [(page.title, page.views) for page in Page.objects.order_by("-views", "title")[:10]]

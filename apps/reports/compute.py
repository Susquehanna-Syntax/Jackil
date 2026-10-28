"""Turning a saved report into dashboard-contract envelopes.

``compute`` takes one card of one report and returns the envelope the
dashboard contract defines, so a report renders wherever a widget does.
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import QueryDict
from django.utils import timezone

from apps.dashboards.contract import envelope
from apps.reports.models import Report
from apps.reports.widgets import QUERIES, REPORT_WIDGETS
from apps.tickets.filters import filter_tickets
from apps.tickets.models import Ticket

STAFF_ROLES = ("agent", "admin")


def visible_reports(user):
    """Reports *user* may open: their own, plus shared ones for staff."""
    if user.role in STAFF_ROLES:
        return Report.objects.filter(Q(owner=user) | Q(shared=True))
    return Report.objects.none()


def report_tickets(report, user):
    """The report's sources applied to the ticket queryset."""
    tickets = Ticket.objects.all()
    departments = list(report.departments.all())
    if departments:
        tickets = tickets.filter(department__in=departments)
    views = list(report.saved_views.all())
    if views:
        pks = set()
        for view in views:
            pks.update(
                filter_tickets(Ticket.objects.all(), QueryDict(view.query), user).values_list(
                    "pk", flat=True
                )
            )
        tickets = tickets.filter(pk__in=pks)
    return tickets


def window(report, today=None):
    """The report's inclusive date window: (start, end) as dates."""
    end = today if today is not None else timezone.localdate()
    start = end - timedelta(days=report.range_days - 1)
    return start, end


def compute(report, index, user, today=None):
    """The contract envelope for card *index* of *report*."""
    if user.role not in STAFF_ROLES:
        raise PermissionDenied("Only agents and admins can view reports.")
    card = report.widgets[index]
    kind = card["kind"]
    try:
        entry = REPORT_WIDGETS[kind]
    except KeyError:
        raise ValueError(f"Unknown report card kind: {kind!r}") from None

    chart = card.get("chart") or entry["chart"]
    x_label = card.get("x_label") or entry["x_label"]
    y_label = card.get("y_label") or entry["y_label"]

    tickets = report_tickets(report, user)
    start, end = window(report, today)
    query = QUERIES[kind]
    if entry["family"] == "days":
        labels, series = query(tickets, start, end)
    else:
        rows = query(tickets)

    if chart == "table":
        if entry["family"] == "days":
            columns = [x_label, *[name for name, _ in series]]
            rows = [[label, *[values[i] for _, values in series]] for i, label in enumerate(labels)]
        else:
            columns = [x_label, y_label]
            rows = [[label, value] for label, value in rows]
        return envelope("table", {"columns": columns, "rows": rows})

    if entry["family"] == "days":
        data = {
            "kind": chart,
            "labels": labels,
            "series": [{"name": name, "values": values} for name, values in series],
        }
    else:
        data = {
            "kind": chart,
            "labels": [label for label, _ in rows],
            "series": [{"name": y_label, "values": [value for _, value in rows]}],
        }
    return envelope("series", data)

"""Turning a saved report into dashboard-contract envelopes.

``compute`` takes one card of one report and returns the envelope the
dashboard contract defines, so a report renders wherever a widget does.
``csv_for`` writes the same answer as CSV, and ``validate_report`` checks
what the builder is about to save.
"""

import csv
import io
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import QueryDict
from django.utils import timezone

from apps.dashboards.contract import envelope
from apps.projects.permissions import can_see_cost, can_see_rates
from apps.reports.models import Report
from apps.reports.widgets import QUERIES, REPORT_WIDGETS
from apps.tickets.filters import filter_tickets
from apps.tickets.models import SavedView, Ticket

STAFF_ROLES = ("agent", "admin")

#: The builder's grid is twelve columns wide.
GRID_COLUMNS = 12
MAX_CARDS = 12
MAX_NAME = 120
MAX_TITLE = 80


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


def report_projects(report):
    """The report's projects, or every project when it names none."""
    from apps.projects.models import Project

    projects = report.projects.all()
    if not projects.exists():
        projects = Project.objects.filter(is_archived=False)
    return projects.order_by("key")


def window(report, today=None):
    """The report's inclusive date window: (start, end) as dates."""
    end = today if today is not None else timezone.localdate()
    start = end - timedelta(days=report.range_days - 1)
    return start, end


def compute(report, index, user, today=None):
    """The contract envelope for card *index* of *report*.

    A ``chart`` the registry does not offer for the kind is a bug in the
    saved widget, so it fails like one — where the card is rendered.
    """
    if user.role not in STAFF_ROLES:
        raise PermissionDenied("Only agents and admins can view reports.")
    card, entry = _card(report, index)

    chart = card.get("chart") or entry["chart"]
    x_label = card.get("x_label") or entry["x_label"]
    y_label = card.get("y_label") or entry["y_label"]

    if _cost_is_hidden(entry, user):
        return envelope("stat", {"value": 0, "label": "Cost hidden", "tone": "muted"})

    source = _source(report, entry, user)
    start, end = window(report, today)
    kind = card["kind"]
    family = entry["family"]
    if family in ("days", "groups"):
        labels, series = QUERIES[kind](source, start, end)
    else:
        rows = QUERIES[kind](source, start, end)

    if chart == "table":
        if family in ("days", "groups"):
            columns = [x_label, *[name for name, _ in series]]
            rows = [[label, *[values[i] for _, values in series]] for i, label in enumerate(labels)]
        else:
            columns = [x_label, y_label]
            rows = [[label, value] for label, value in rows]
        if entry.get("money"):
            rows = [[row[0], *[f"{value:.2f}" for value in row[1:]]] for row in rows]
        return envelope("table", {"columns": columns, "rows": rows})

    if family in ("days", "groups"):
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


def csv_for(report, index, user, today=None):
    """Card *index* of *report* as CSV: a header line and one line per row.

    The header comes from the card's labels, which the envelope itself does
    not carry — hence the second look at the card for a series.
    """
    result = compute(report, index, user, today=today)
    data = result["data"]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    if result["shape"] == "table":
        writer.writerow(data["columns"])
        writer.writerows(data["rows"])
    elif result["shape"] == "series":
        card, entry = _card(report, index)
        header = [card.get("x_label") or entry["x_label"], *[s["name"] for s in data["series"]]]
        writer.writerow(header)
        for i, label in enumerate(data["labels"]):
            writer.writerow([label, *[s["values"][i] for s in data["series"]]])
    else:
        writer.writerow(["Value"])
        writer.writerow([data["label"]])
    return out.getvalue()


def validate_report(payload, user):
    """Plain-words errors for a builder payload; an empty list means it is good.

    A saved view is checked twice over: that the id names a view at all, and
    that it is one *you* may use — saving someone else's private view would be
    handing them your filters.
    """
    errors = []
    name = str(payload.get("name") or "").strip()
    if not name:
        errors.append("Give the report a name.")
    elif len(name) > MAX_NAME:
        errors.append(f"Names are at most {MAX_NAME} characters.")

    days = _int_or_none(payload.get("range_days"))
    if days not in Report.RANGES:
        errors.append("Pick a range of 7, 14, 30, 90, 180 or 365 days.")

    cards = payload.get("widgets") or []
    if len(cards) > MAX_CARDS:
        errors.append(f"A report holds at most {MAX_CARDS} cards.")

    for number, card in enumerate(cards[:MAX_CARDS], start=1):
        errors.extend(_card_errors(card, number, user))

    errors.extend(_source_errors(payload, user))
    return errors


def _card(report, index):
    """The card at *index* and its registry entry."""
    card = report.widgets[index]
    kind = card["kind"]
    try:
        return card, REPORT_WIDGETS[kind]
    except KeyError:
        raise ValueError(f"Unknown report card kind: {kind!r}") from None


def _cost_is_hidden(entry, user) -> bool:
    needs = entry.get("needs")
    if needs == "cost":
        return not can_see_cost(user)
    if needs == "rates":
        return not can_see_rates(user)
    return False


def _source(report, entry, user):
    source = entry.get("source", "tickets")
    if source == "projects":
        return report_projects(report)
    if source == "wiki":
        return None
    return report_tickets(report, user)


def _card_errors(card, number, user):
    errors = []
    kind = card.get("kind") if isinstance(card, dict) else None
    entry = REPORT_WIDGETS.get(kind)
    if entry is None:
        errors.append(f"Card {number}: unknown kind.")
        return errors

    if card.get("chart") and card["chart"] not in entry["charts"]:
        errors.append(f"Card {number}: that chart does not suit this card.")

    title = card.get("title")
    if title is not None and len(str(title)) > MAX_TITLE:
        errors.append(f"Card {number}: titles are at most {MAX_TITLE} characters.")

    errors.extend(_grid_errors(card, entry, number))

    if entry.get("needs") == "cost" and not can_see_cost(user):
        errors.append(f"Card {number}: you can't add cost cards.")
    if entry.get("needs") == "rates" and not can_see_rates(user):
        errors.append(f"Card {number}: only admins can add cost-per-point cards.")
    return errors


def _grid_errors(card, entry, number):
    """Placement errors, judged with the card's registry size when it gives none."""
    w = _grid_number(card, "w")
    h = _grid_number(card, "h")
    x = _grid_number(card, "x") or 0
    if w is None:
        w = entry["size"]["w"]
    if h is None:
        h = entry["size"]["h"]
    if not _in_range(w, 1, 12) or not _in_range(h, 1, 24):
        return [f"Card {number}: width is 1 to 12 and height 1 to 24."]
    if x + w > GRID_COLUMNS:
        return [f"Card {number}: it runs off the right of the grid."]
    return []


def _grid_number(card, key):
    """The card's grid number as a whole number; None when it isn't one."""
    value = card.get(key)
    number = _int_or_none(value)
    if number is None or (isinstance(value, float) and not value.is_integer()):
        return None
    return number


def _source_errors(payload, user):
    from apps.accounts.models import Department
    from apps.projects.models import Project

    missing = False
    for model, key in ((Department, "departments"), (Project, "projects")):
        missing = missing or _ids_are_unknown(payload.get(key), model)

    view_ids = _valid_ids(payload.get("saved_views"))
    if view_ids:
        missing = missing or _ids_are_unknown(view_ids, SavedView)
    foreign_view = False
    if view_ids:
        usable = set(
            SavedView.objects.filter(
                Q(owner=user) | Q(is_shared=True), pk__in=view_ids
            ).values_list("pk", flat=True)
        )
        foreign_view = any(pk not in usable for pk in view_ids)

    errors = []
    if missing:
        errors.append("A department, project or saved view in the sources does not exist.")
    if foreign_view:
        errors.append("A saved view in the sources is not yours to use.")
    return errors


def _valid_ids(value):
    """The entries of *value* that name an id; junk entries are not ids."""
    if not isinstance(value, (list, tuple)):
        return []
    ids = []
    for pk in value:
        number = _int_or_none(pk)
        if number is not None:
            ids.append(number)
    return ids


def _ids_are_unknown(ids, model):
    """True when the list holds something that is not the id of a row."""
    if not isinstance(ids, (list, tuple)):
        return False
    known = set(model.objects.filter(pk__in=_valid_ids(ids)).values_list("pk", flat=True))
    return any(pk not in known for pk in _valid_ids(ids))


def _in_range(value, low, high) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

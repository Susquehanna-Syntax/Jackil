"""The report builder: one page where the owner changes everything about a report."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render

from apps.accounts.models import Department
from apps.projects.models import Project
from apps.projects.permissions import can_see_cost, can_see_rates
from apps.reports.compute import validate_report, visible_reports
from apps.reports.models import Report
from apps.reports.widgets import GROUPS, REPORT_WIDGETS
from apps.tickets.models import SavedView

STAFF_ROLES = ("agent", "admin")


def _may_see(entry, user) -> bool:
    needs = entry.get("needs")
    if needs == "cost":
        return can_see_cost(user)
    if needs == "rates":
        return can_see_rates(user)
    return True


@login_required
def report_edit(request, report_id):
    """Everything about one report, on one page. Only its owner may change it."""
    if request.user.role not in STAFF_ROLES:
        return redirect("tickets:dashboard")
    report = visible_reports(request.user).filter(id=report_id).first()
    if report is None:
        raise Http404("No such report.")
    if report.owner_id != request.user.pk:
        raise PermissionDenied("Only the owner can change this report.")

    post = request.POST if request.method == "POST" else None
    if post is not None and post.get("action") == "delete":
        report.delete()
        messages.success(request, "Report deleted.")
        return redirect("reports:reports_home")

    add_kind = post.get("add_kind", "").strip() if post is not None else ""
    widgets = _cards(post) if post is not None else _saved_cards(report)
    # The new card joins what gets validated, so it is refused in words rather
    # than saved and only refused when the page next opens.
    if REPORT_WIDGETS.get(add_kind) is not None:
        widgets = [*widgets, {"kind": add_kind}]

    values = _values(report, post, widgets)
    errors = validate_report(values, request.user) if post is not None else []
    if errors:
        return _render(request, report, values, errors)

    if post is not None:
        _save(report, values)
        messages.success(request, "Report saved.")
        if add_kind:
            return redirect("reports:report_edit", report_id=report.pk)
        return redirect("reports:report_page", report_id=report.pk)

    return _render(request, report, values, [])


def _save(report, values):
    report.name = values["name"].strip()
    report.description = values["description"]
    report.shared = values["shared"]
    report.range_days = int(values["range_days"])
    report.widgets = values["widgets"]
    report.save()
    for key in ("departments", "projects", "saved_views"):
        getattr(report, key).set(values[key])


def _values(report, post, widgets):
    """What to show and save: the posted form, or the report as it stands."""
    if post is None:
        return {
            "name": report.name,
            "description": report.description,
            "shared": report.shared,
            "range_days": report.range_days,
            "departments": list(report.departments.values_list("pk", flat=True)),
            "projects": list(report.projects.values_list("pk", flat=True)),
            "saved_views": list(report.saved_views.values_list("pk", flat=True)),
            "widgets": widgets,
        }
    return {
        "name": post.get("name", ""),
        "description": post.get("description", ""),
        "shared": post.get("shared") == "on",
        "range_days": post.get("range_days"),
        "departments": _ids(post, "departments"),
        "projects": _ids(post, "projects"),
        "saved_views": _ids(post, "saved_views"),
        "widgets": widgets,
    }


def _saved_cards(report):
    return [dict(card) for card in report.widgets if isinstance(card, dict)]


def _cards(post):
    """The surviving cards, in posted order by their order field."""
    try:
        count = int(post.get("card_count", "0"))
    except ValueError:
        count = 0

    cards = []
    for i in range(max(count, 0)):
        if post.get(f"card-{i}-remove") == "on":
            continue
        row = _card(post, i)
        order = _int_or_none(post.get(f"card-{i}-order"))
        cards.append((row, i if order is None else order))

    # Timsort is stable, so tied orders keep the position they were posted in.
    return [row for row, _ in sorted(cards, key=lambda pair: pair[1])]


def _card(post, i):
    """One posted card row as a saved card dict."""
    kind = post.get(f"card-{i}-kind", "")
    entry = REPORT_WIDGETS.get(kind)
    card = {"kind": kind}

    # A select always posts one of its own values, so the kind's default chart
    # cannot be told apart from a pick of it; saving it is how the rest of the
    # app spells "the default chart" (the API writes it into new cards too).
    chart = post.get(f"card-{i}-chart", "").strip()
    if entry is not None and (not chart or chart not in entry["charts"]):
        chart = entry["chart"]
    if chart:
        card["chart"] = chart

    for field in ("title", "x_label", "y_label"):
        value = post.get(f"card-{i}-{field}", "").strip()
        if value:
            card[field] = value

    for size in ("w", "h"):
        number = _int_or_none(post.get(f"card-{i}-{size}"))
        if number is not None:
            card[size] = number
    return card


def _ids(post, key):
    return [pk for pk in (_int_or_none(v) for v in post.getlist(key)) if pk is not None]


def _source_rows(queryset, name_of, chosen):
    """One of the three source lists, with the report's own ticks marked."""
    return [{"id": obj.pk, "name": name_of(obj), "checked": obj.pk in chosen} for obj in queryset]


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _render(request, report, values, errors):
    """The editor, showing *values* — the saved ones on GET, the posted ones back."""
    user = request.user
    cards = []
    for index, card in enumerate(values["widgets"]):
        entry = REPORT_WIDGETS.get(card.get("kind"))
        if entry is None:
            continue
        cards.append(
            {
                "index": index,
                "order": index + 1,
                "kind": card["kind"],
                "chart": card.get("chart") or entry["chart"],
                "charts": entry["charts"],
                "title": card.get("title", ""),
                "x_label": card.get("x_label", ""),
                "y_label": card.get("y_label", ""),
                "w": card.get("w", entry["size"]["w"]),
                "h": card.get("h", entry["size"]["h"]),
                "how": entry["how"],
                "registry_title": entry["title"],
                "x_label_placeholder": entry["x_label"],
                "y_label_placeholder": entry["y_label"],
                "kind_options": _kind_options(user, selected=card.get("kind")),
            }
        )

    return render(
        request,
        "reports/edit.html",
        {
            "report": report,
            "errors": errors,
            "cards": cards,
            "ranges": Report.RANGES,
            "add_kind": "",
            "add_options": _kind_options(user),
            "name": values["name"],
            "description": values["description"],
            "shared": values["shared"],
            "range_days": values["range_days"],
            "departments": _source_rows(
                Department.objects.order_by("name"), lambda row: row.name, values["departments"]
            ),
            "projects": _source_rows(
                Project.objects.filter(is_archived=False).order_by("key"),
                lambda row: f"{row.key} — {row.name}",
                values["projects"],
            ),
            "saved_views": _source_rows(
                SavedView.objects.filter(Q(owner=user) | Q(is_shared=True)).order_by("name"),
                lambda row: row.name,
                values["saved_views"],
            ),
        },
    )


def _kind_options(user, selected=None):
    """The registry's kinds grouped for a ``<select>``, minus the ones you lack."""
    options = []
    for group in GROUPS:
        rows = [
            {"kind": kind, "title": entry["title"]}
            for kind, entry in REPORT_WIDGETS.items()
            if entry["group"] == group and (kind == selected or _may_see(entry, user))
        ]
        if rows:
            options.append({"group": group, "kinds": rows})
    return options

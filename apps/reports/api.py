"""The reports JSON API: list, create, read, change, delete, data and CSV.

Everything here answers with the plain dicts the browser script paints from;
the report's visibility rules, its card computation and the validation of a
saved payload all live in ``apps.reports.compute``.
"""

from django.http import HttpResponse
from django.utils.text import slugify
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.dashboards.permissions import IsStaffRole
from apps.projects.permissions import can_see_cost, can_see_rates
from apps.reports.compute import compute, csv_for, validate_report, visible_reports
from apps.reports.models import Report
from apps.reports.widgets import GROUPS, REPORT_WIDGETS

#: What the "New report" button and a POST without cards start with.
DEFAULT_CARDS = [
    {"kind": "ticket_volume"},
    {"kind": "status_mix"},
    {"kind": "sla_compliance"},
    {"kind": "agent_load"},
]

#: The builder-editable fields a PATCH may carry; anything else is ignored.
PATCHABLE = (
    "name",
    "description",
    "shared",
    "range_days",
    "widgets",
    "departments",
    "projects",
    "saved_views",
)

FORBIDDEN = "Only the owner can change this report."


def _row(report, user):
    """One report in the shape the API and the page scripts use."""
    return {
        "id": str(report.id),
        "name": report.name,
        "description": report.description,
        "shared": report.shared,
        "range_days": report.range_days,
        "widgets": report.widgets,
        "departments": [d.pk for d in report.departments.all()],
        "projects": [p.pk for p in report.projects.all()],
        "saved_views": [v.pk for v in report.saved_views.all()],
        "owner": report.owner.username,
        "can_edit": report.owner_id == user.pk,
        "updated_at": report.updated_at.isoformat(),
    }


def _visible(report_id, user):
    """The report *report_id* names, when *user* may see it; else ``None``."""
    return visible_reports(user).filter(id=report_id).first()


def _set_sources(report, data):
    for key in ("departments", "projects", "saved_views"):
        if key in data:
            getattr(report, key).set(data[key] or [])


def _source_ids(changes, related, key):
    """The PATCH's ids for one source, or the report's current ones."""
    if key in changes:
        return changes[key] or []
    return list(related.values_list("pk", flat=True))


@api_view(["GET", "POST"])
@permission_classes([IsStaffRole])
def report_index(request):
    """Every report the caller can see, and the way to make a new one."""
    if request.method == "GET":
        return Response([_row(r, request.user) for r in visible_reports(request.user)])

    data = request.data
    errors = validate_report(data, request.user)
    if errors:
        return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

    cards = data.get("widgets") or []
    report = Report.objects.create(
        owner=request.user,
        name=str(data.get("name") or "").strip(),
        description=data.get("description") or "",
        shared=bool(data.get("shared")),
        range_days=int(data.get("range_days")),
        widgets=cards if cards else DEFAULT_CARDS,
    )
    _set_sources(report, data)
    return Response(_row(report, request.user), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsStaffRole])
def report_detail(request, report_id):
    """One report. Reading follows visibility; writing is owner-only."""
    report = _visible(report_id, request.user)
    if report is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(_row(report, request.user))

    if report.owner_id != request.user.pk:
        return Response({"detail": FORBIDDEN}, status=status.HTTP_403_FORBIDDEN)

    if request.method == "DELETE":
        report.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    changes = {key: value for key, value in request.data.items() if key in PATCHABLE}
    merged = {
        "name": changes.get("name", report.name),
        "description": changes.get("description", report.description),
        "shared": changes.get("shared", report.shared),
        "range_days": changes.get("range_days", report.range_days),
        "widgets": changes.get("widgets", report.widgets),
        "departments": _source_ids(changes, report.departments, "departments"),
        "projects": _source_ids(changes, report.projects, "projects"),
        "saved_views": _source_ids(changes, report.saved_views, "saved_views"),
    }
    errors = validate_report(merged, request.user)
    if errors:
        return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

    for key in ("name", "description", "shared"):
        if key in changes:
            setattr(report, key, changes[key])
    if "range_days" in changes:
        report.range_days = int(changes["range_days"])
    if "widgets" in changes:
        report.widgets = changes["widgets"] or []
    _set_sources(report, changes)
    report.save()
    return Response(_row(report, request.user))


@api_view(["GET"])
@permission_classes([IsStaffRole])
def widget_catalog(request):
    """The card kinds, grouped for the builder's rail.

    A cost card is *listed* even when the caller may not use it — the rail
    shows it greyed out rather than hiding a whole group from agents.
    """
    user = request.user
    widgets = {}
    for kind, entry in REPORT_WIDGETS.items():
        widgets[kind] = {
            "title": entry["title"],
            "description": entry["description"],
            "chart": entry["chart"],
            "charts": entry["charts"],
            "family": entry["family"],
            "group": entry["group"],
            "x_label": entry["x_label"],
            "y_label": entry["y_label"],
            "how": entry["how"],
            "size": entry["size"],
            "available": _is_available(entry, user),
        }
    return Response({"groups": GROUPS, "widgets": widgets})


@api_view(["GET"])
@permission_classes([IsStaffRole])
def report_data(request, report_id, index):
    """Card *index* of *report*, as a contract envelope."""
    report = _visible(report_id, request.user)
    if report is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    try:
        return Response(compute(report, index, request.user))
    except IndexError:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsStaffRole])
def report_data_csv(request, report_id, index):
    """Card *index* of *report*, as a downloadable CSV file."""
    report = _visible(report_id, request.user)
    if report is None:
        return HttpResponse("Not found.", status=status.HTTP_404_NOT_FOUND)

    try:
        body = csv_for(report, index, request.user)
    except IndexError:
        return HttpResponse("Not found.", status=status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return HttpResponse(str(exc), status=status.HTTP_400_BAD_REQUEST)

    filename = f"{slugify(report.name)}-{index + 1}.csv"
    response = HttpResponse(body, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _is_available(entry, user):
    needs = entry.get("needs")
    if needs == "cost":
        return can_see_cost(user)
    if needs == "rates":
        return can_see_rates(user)
    return True

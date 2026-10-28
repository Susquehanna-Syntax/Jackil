"""The project reports page: burndown, velocity, cumulative flow and cost."""

import csv

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render

from apps.dashboards.contract import envelope

from . import metrics, permissions
from .models import CostSettings, Project, Sprint

#: The days cumulative-flow accepts; anything else is clamped into this range.
FLOW_DAYS = (7, 90)

#: Groupings the cost card offers; "person" needs can_see_rates, so it is added first.
COST_GROUPINGS = [("epic", "Epic"), ("sprint", "Sprint")]


@login_required
def reports_page(request, key):
    """The reports screen: one card per report, each painted from its endpoint."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())
    can_see_rates = permissions.can_see_rates(request.user)
    groupings = list(COST_GROUPINGS)
    if can_see_rates:
        groupings.insert(0, ("person", "Person"))
    return render(
        request,
        "projects/reports.html",
        {
            "project": project,
            "sprints": _sprints(project),
            "can_see_cost": permissions.can_see_cost(request.user),
            "can_see_rates": can_see_rates,
            "currency": CostSettings.get_solo().currency,
            "groupings": groupings,
        },
    )


@login_required
def reports_data(request, key, name):
    """One report's widget envelope; the page fetches each card separately."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())

    if name == "burndown":
        return JsonResponse(envelope("series", _burndown(project, request.GET.get("sprint"))))
    if name == "velocity":
        return JsonResponse(envelope("series", metrics.velocity_chart(project)))
    if name == "flow":
        payload = metrics.cumulative_flow(project, days=_days(request.GET.get("days")))
        return JsonResponse(envelope("series", payload))
    if name == "cost":
        by = request.GET.get("by", "epic")
        try:
            payload = metrics.cost_breakdown(project, by, request.user)
        except ValueError:
            return JsonResponse({"error": "Unknown cost grouping."}, status=400)
        return JsonResponse(envelope("table", payload))
    return JsonResponse({"error": "No such report."}, status=404)


@login_required
def reports_cost_csv(request, key):
    """The cost table as a downloadable file; the same permission rules apply."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())
    by = request.GET.get("by", "epic")
    try:
        payload = metrics.cost_breakdown(project, by, request.user)
    except ValueError:
        return HttpResponse("Unknown cost grouping.", status=400, content_type="text/plain")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{project.key}-cost-{by}.csv"'
    writer = csv.writer(response)
    writer.writerow(payload["columns"])
    for row in payload["rows"]:
        writer.writerow(row)
    return response


def _sprints(project):
    """The dated sprints the burndown can draw: active first, then by most recent day."""
    ordered = sorted(
        project.sprints.exclude(start_date=None),
        key=lambda sprint: (_rank(sprint), -_recency(sprint), -sprint.pk),
    )
    return ordered[:10]


def _rank(sprint):
    """Active sprints first, then closed ones, then anything merely planned."""
    if sprint.state == "active":
        return 0
    return 1 if sprint.closed_at is not None else 2


def _recency(sprint):
    """The day the sprint last mattered: it closed on, or else it starts on."""
    if sprint.closed_at is not None:
        return sprint.closed_at.date().toordinal()
    return sprint.start_date.toordinal()


def _burndown(project, sprint_id):
    """The named sprint of this project's burndown, or the page's first sprint."""
    if sprint_id not in (None, ""):
        sprint = get_object_or_404(Sprint, pk=_int_or_none(sprint_id), project=project)
        return metrics.burndown(sprint)
    sprints = _sprints(project)
    return metrics.burndown(sprints[0]) if sprints else _empty_series()


def _empty_series():
    return {"kind": "line", "labels": [], "series": []}


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _days(value):
    try:
        days = int(value)
    except (TypeError, ValueError):
        return 30
    return max(FLOW_DAYS[0], min(FLOW_DAYS[1], days))

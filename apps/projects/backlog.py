"""Backlog, sprint planning and load per person: the JSON the screen runs on.

Money never appears here. Load is committed story points against velocity, and
velocity is a points-per-sprint average — wages and costs stay in the admin.
"""

import json
from datetime import date, datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import cost, permissions, service
from .models import Issue, Project, Sprint
from .views import display_name, issue_url


@login_required
def backlog_page(request, key):
    """The Scrum planning screen. A Kanban project has a board instead (phase 04)."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())
    if project.method != "scrum":
        return redirect("projects:board", key=project.key)
    return render(
        request,
        "projects/backlog.html",
        {
            "project": project,
            "sprints": _sprint_rows(project),
            "data_url": reverse("projects:backlog_data", args=[project.key]),
            "rank_url": reverse("projects:backlog_rank", args=[project.key]),
            "create_url": reverse("projects:sprint_create", args=[project.key]),
        },
    )


@login_required
def backlog_data(request, key):
    """Everything the planning screen draws: sprints, backlog and load."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())
    sprints = _sprint_rows(project)
    by_sprint = {}
    for issue in Issue.objects.filter(project=project).select_related("project", "assignee"):
        by_sprint.setdefault(issue.sprint_id, []).append(issue)
    return JsonResponse(
        {
            "sprints": [
                _sprint_json(sprint, sorted(by_sprint.get(sprint.id, []), key=_display_order))
                for sprint in sprints
            ],
            "backlog": [
                _issue_row(issue) for issue in sorted(by_sprint.get(None, []), key=_display_order)
            ],
            "people": _people(project, _planning_sprint(project, sprints)),
        }
    )


def _display_order(issue):
    return (issue.rank, issue.number)


def _sprint_json(sprint, issues):
    return {
        "id": sprint.id,
        "name": sprint.name,
        "goal": sprint.goal,
        "state": sprint.state,
        "start_date": _iso(sprint.start_date),
        "end_date": _iso(sprint.end_date),
        "issues": [_issue_row(issue) for issue in issues],
        "points": sum(i.story_points or 0 for i in issues if i.type != "subtask"),
    }


def _issue_row(issue):
    return {
        "id": issue.id,
        "key": issue.key,
        "title": issue.title,
        "type": issue.type,
        "points": issue.story_points,
        "assignee": issue.assignee_id,
        "assignee_name": display_name(issue.assignee) if issue.assignee_id else "",
        "url": issue_url(issue),
        "column": issue.column_id,
        "rank": issue.rank,
    }


@login_required
def backlog_rank(request, key):
    """Move an issue into a sprint (or the backlog) and rank it just above another."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    project = get_object_or_404(Project, key=key.upper())
    payload = _body(request)

    issue = get_object_or_404(Issue, pk=_int_or_none(payload.get("issue")), project=project)
    if issue.type == "subtask":
        return JsonResponse(
            {"error": "Sub-tasks follow their parent. Rank the parent instead."},
            status=400,
        )

    target, error = _target_sprint(project, payload.get("sprint"))
    if error:
        return JsonResponse({"error": error}, status=400)

    moved = issue.sprint_id != (target.pk if target is not None else None)
    before, error = _before_issue(project, payload.get("before"), target)
    if error:
        return JsonResponse({"error": error}, status=400)

    try:
        with transaction.atomic():
            if moved:
                service.set_sprint(request.user, issue, target)
            service.rank_between(issue, _list_rows(project, target), before)
    except ValidationError as exc:
        return JsonResponse({"error": _message(exc)}, status=400)
    return JsonResponse({"ok": True})


@login_required
def sprint_create(request, key):
    """A new planned sprint; the name defaults to "<KEY> Sprint <n>"."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    project = get_object_or_404(Project, key=key.upper())
    payload = _body(request)
    name = (
        str(payload.get("name") or "").strip() or f"{project.key} Sprint {_sprint_number(project)}"
    )
    sprint = Sprint.objects.create(
        project=project,
        name=name[:120],
        goal=str(payload.get("goal") or "").strip()[:300],
    )
    return JsonResponse({"id": sprint.id, "name": sprint.name}, status=201)


@login_required
def sprint_start(request, key, id):
    """Start a sprint on a chosen pair of dates."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    project = get_object_or_404(Project, key=key.upper())
    sprint = get_object_or_404(Sprint, pk=id, project=project)
    payload = _body(request)

    start, error = _date_or_error(payload.get("start_date"), "start date")
    if error:
        return JsonResponse({"error": error}, status=400)
    end, error = _date_or_error(payload.get("end_date"), "end date")
    if error:
        return JsonResponse({"error": error}, status=400)
    if end < start:
        return JsonResponse({"error": "The end date cannot be before the start date."}, status=400)

    try:
        service.start_sprint(request.user, sprint, start, end)
    except ValidationError as exc:
        return JsonResponse({"error": _message(exc)}, status=400)
    return JsonResponse({"ok": True})


@login_required
def sprint_complete(request, key, id):
    """Close a sprint; open work goes to the chosen sprint or back to the backlog."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    project = get_object_or_404(Project, key=key.upper())
    sprint = get_object_or_404(Sprint, pk=id, project=project)
    open_count = sprint.issues.exclude(column__category="done").count()
    payload = _body(request)

    target, error = _target_sprint(project, payload.get("move_open_to"))
    if error:
        return JsonResponse({"error": error}, status=400)
    try:
        service.complete_sprint(request.user, sprint, move_open_to=target)
    except ValidationError as exc:
        return JsonResponse({"error": _message(exc)}, status=400)
    return JsonResponse({"moved": open_count})


@login_required
def sprint_edit(request, key, id):
    """Rename a sprint, change its goal or its dates. A closed sprint is settled."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    project = get_object_or_404(Project, key=key.upper())
    sprint = get_object_or_404(Sprint, pk=id, project=project)
    if sprint.state == "closed":
        return JsonResponse({"error": "A closed sprint cannot be edited."}, status=400)

    payload = _body(request)
    fields = []
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return JsonResponse({"error": "A sprint needs a name."}, status=400)
        sprint.name = name[:120]
        fields.append("name")
    if "goal" in payload:
        sprint.goal = str(payload.get("goal") or "").strip()[:300]
        fields.append("goal")
    for field, label in (("start_date", "start date"), ("end_date", "end date")):
        if field in payload:
            value, error = _date_or_error(payload.get(field), label)
            if error:
                return JsonResponse({"error": error}, status=400)
            setattr(sprint, field, value)
            fields.append(field)
    if sprint.start_date and sprint.end_date and sprint.end_date < sprint.start_date:
        return JsonResponse({"error": "The end date cannot be before the start date."}, status=400)
    sprint.save(update_fields=fields)
    return JsonResponse({"ok": True})


def _sprint_rows(project):
    """Planned and active sprints — the active one first, then by creation."""
    sprints = list(project.sprints.filter(state__in=["active", "planned"]))
    sprints.sort(key=lambda sprint: (sprint.state != "active", sprint.id))
    return sprints


def _planning_sprint(project, sprints):
    """Whose load to show: the active sprint, else the first planned one."""
    for sprint in sprints:
        if sprint.state == "active":
            return sprint
    return project.sprints.filter(state="planned").order_by("id").first()


def _people(project, sprint):
    """Everyone committed to the sprint, points against their usual velocity.

    The project lead is listed even at zero: they are who gets handed the
    overflow. Sub-tasks carry no points of their own, so only their parent's
    assignee and points count here.
    """
    people = {}
    committed = {}

    def add(user):
        entry = people.get(user.pk)
        if entry is None:
            entry = {
                "id": user.pk,
                "name": user.get_full_name() or user.username,
                "committed": 0,
                "velocity": _velocity_of(user),
            }
            people[user.pk] = entry
            committed[user.pk] = 0
        return entry

    if project.lead is not None:
        add(project.lead)
    if sprint is not None:
        for issue in sprint.issues.select_related("assignee"):
            if issue.type == "subtask" or issue.assignee_id is None:
                continue
            add(issue.assignee)
            committed[issue.assignee_id] += issue.story_points or 0

    return sorted(
        (dict(entry, committed=committed[entry["id"]]) for entry in people.values()),
        key=lambda row: (-row["committed"], row["name"], row["id"]),
    )


def _velocity_of(user):
    value = cost.velocity(user)
    return None if value is None else float(value)


def _list_rows(project, target):
    """The list being ranked in — a sprint, or the backlog — in display order."""
    issues = Issue.objects.filter(project=project)
    if target is not None:
        issues = issues.filter(sprint=target)
    else:
        issues = issues.filter(sprint__isnull=True)
    return list(issues.order_by("rank", "number"))


def _target_sprint(project, sprint_id):
    """The sprint a payload names, as (sprint or None, error or None)."""
    if sprint_id in (None, ""):
        return None, None
    pk = _int_or_none(sprint_id)
    sprint = Sprint.objects.filter(pk=pk, project=project).first() if pk is not None else None
    if sprint is None:
        return None, "That sprint is not in this project."
    if sprint.state == "closed":
        return None, "Cannot add issues to a closed sprint."
    return sprint, None


def _before_issue(project, before_id, target):
    """The issue to rank against, which has to live in the list being ranked."""
    if before_id in (None, ""):
        return None, None
    pk = _int_or_none(before_id)
    before = Issue.objects.filter(pk=pk, project=project).first() if pk is not None else None
    if before is None:
        return None, "The issue to rank against is not in this project."
    wanted = target.pk if target is not None else None
    if before.sprint_id != wanted:
        return None, "The issue to rank against is in another list."
    return before, None


def _sprint_number(project) -> int:
    """One past the number the existing sprints use, so default names do not repeat."""
    highest = 0
    for name in project.sprints.values_list("name", flat=True):
        tail = name.rsplit("Sprint", 1)[-1].strip() if "Sprint" in name else ""
        if tail.isdigit():
            highest = max(highest, int(tail))
    return highest + 1


def _body(request) -> dict:
    try:
        parsed = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _int_or_none(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date_or_error(value, label):
    """An ISO date from the payload — the form a `<input type="date">` sends."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value, None
    if not isinstance(value, str):
        return None, f"Give a {label} as a date, like 2026-11-02."
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date(), None
    except ValueError:
        return None, f"Give a {label} as a date, like 2026-11-02."


def _iso(value):
    return value.isoformat() if value else None


def _message(exc):
    errors = getattr(exc, "error_dict", None)
    if errors:
        for messages in errors.values():
            return messages[0]
    messages = getattr(exc, "error_list", [])
    return str(messages[0]) if messages else "That did not work."

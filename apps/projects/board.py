"""The board: its columns and cards, and the endpoint that moves a card between them."""

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from . import permissions, service, views
from .models import Column, Issue, Project


@login_required
def board_page(request, key):
    """The board screen: one column per project Column, cards you drag between them."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())
    return render(
        request,
        "projects/board.html",
        {
            "project": project,
            "data_url": reverse("projects:board_data", args=[project.key]),
            "move_url": reverse("projects:board_move", args=[project.key]),
            "backlog_url": reverse("projects:backlog", args=[project.key])
            if project.method == "scrum"
            else "",
        },
    )


@login_required
def board_data(request, key):
    """The columns and cards the board draws."""
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())
    sprint = _active_sprint(project)
    columns = list(project.columns.all())
    grouped = _group_by_column(_cards(project, request.GET.dict(), request.user), columns)
    return JsonResponse(
        {
            "method": project.method,
            "sprint": (
                {"id": sprint.id, "name": sprint.name, "end_date": _date(sprint.end_date)}
                if sprint is not None
                else None
            ),
            "columns": [_column(column, grouped.get(column.id, [])) for column in columns],
        }
    )


@login_required
def board_move(request, key):
    """Move a card to another column and rank it above the card the client names."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())
    payload = _body(request)

    issue = get_object_or_404(Issue, pk=_int_or_none(payload.get("issue")), project=project)
    if issue.type == "subtask":
        return JsonResponse({"error": "Sub-tasks move with their parent's card."}, status=400)
    column = get_object_or_404(Column, pk=_int_or_none(payload.get("column")), project=project)

    cards = _cards(project, {}, request.user)
    siblings = [card for card in cards if card.column_id == column.pk and card.pk != issue.pk]
    before, error = _before_card(siblings, issue, payload.get("before"))
    if error:
        return JsonResponse({"error": error}, status=400)

    if project.method != "scrum" and column.wip_limit is not None and not payload.get("force"):
        if len(siblings) >= column.wip_limit:
            return JsonResponse(
                {
                    "error": f"{column.name} is at its limit of {column.wip_limit}.",
                    "wip": True,
                },
                status=409,
            )

    try:
        with transaction.atomic():
            service.move_issue(request.user, issue, column)
            service.rank_between(issue, siblings, before)
    except ValidationError as exc:
        return JsonResponse({"error": _message(exc)}, status=400)
    return JsonResponse({"ok": True, "category": column.category})


def _active_sprint(project):
    """The sprint Scrum boards draw, or None: Kanban boards never have one."""
    if project.method != "scrum":
        return None
    return project.sprints.filter(state="active").first()


def _cards(project, query, user):
    """The issues the board draws as cards: the method's rules first, then the filters."""
    cards = (
        Issue.objects.filter(project=project)
        .exclude(type="subtask")
        .select_related("assignee", "column", "project")
        .prefetch_related("children__column")
    )
    active = _active_sprint(project)
    if project.method == "scrum":
        cards = cards.filter(sprint=active) if active is not None else cards.none()
    else:
        # A join-based exclude would duplicate the null-sprint rows through the LEFT JOIN.
        closed = project.sprints.filter(state="closed").values_list("pk", flat=True)
        cards = cards.exclude(sprint__in=closed)

    person = _assignee_filter(query.get("assignee"), user)
    if person == "me":
        cards = cards.filter(assignee=user)
    elif person is not None:
        cards = cards.filter(assignee_id=person)

    issue_type = query.get("type")
    if issue_type and issue_type in dict(Issue.TYPE_CHOICES):
        cards = cards.filter(type=issue_type)

    search = (query.get("q") or "").strip()
    if search:
        cards = cards.filter(title__icontains=search)

    return list(cards.order_by("rank", "number"))


def _assignee_filter(value, user):
    """A user id, the request user for "me", or None when the value is not usable."""
    token = (value or "").strip()
    if not token:
        return None
    if token == "me":
        return "me" if user.is_authenticated else None
    try:
        return int(token)
    except ValueError:
        return None


def _group_by_column(cards, columns):
    """Cards by column id; one with no column of its own sits in the first column."""
    fallback = columns[0].id if columns else None
    grouped = {}
    for card in cards:
        grouped.setdefault(card.column_id if card.column_id is not None else fallback, []).append(
            card
        )
    return grouped


def _column(column, cards):
    return {
        "id": column.id,
        "name": column.name,
        "category": column.category,
        "wip_limit": column.wip_limit,
        "count": len(cards),
        "issues": [_card(issue) for issue in cards],
    }


def _card(issue):
    children = [child for child in issue.children.all() if child.type == "subtask"]
    return {
        "id": issue.id,
        "key": issue.key,
        "title": issue.title,
        "type": issue.type,
        "points": issue.story_points,
        "assignee": _person(issue.assignee),
        "priority": issue.priority,
        "url": views.issue_url(issue),
        "subtasks_done": sum(
            1 for child in children if child.column is not None and child.column.category == "done"
        ),
        "subtasks_total": len(children),
    }


def _person(person):
    if person is None:
        return None
    return {
        "id": person.id,
        "name": views.display_name(person),
        "initials": person.avatar_initials,
        "color": person.avatar_color,
    }


def _before_card(cards, issue, before_id):
    """The card to rank above; it has to be a card in the column being dropped into."""
    if before_id in (None, ""):
        return None, None
    pk = _int_or_none(before_id)
    before = next((card for card in cards if card.pk == pk), None) if pk is not None else None
    if before is None or before.pk == issue.pk:
        return None, "The card to rank against is not in that column."
    return before, None


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


def _date(value):
    return value.isoformat() if value is not None else None


def _message(exc):
    errors = getattr(exc, "error_dict", None)
    if errors:
        for messages in errors.values():
            return messages[0]
    messages = getattr(exc, "error_list", [])
    return str(messages[0]) if messages else "That did not work."

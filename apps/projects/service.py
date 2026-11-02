"""Projects service: permissions, numbering, and everything worth an event."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, When
from django.utils import timezone

from . import cost
from .models import Column, Issue, IssueEvent, Project, Sprint

DEFAULT_COLUMNS = [("To do", "todo"), ("In progress", "in_progress"), ("Done", "done")]

#: Two ranks this close together cannot be split again by a midpoint.
RANK_EPSILON = 1e-6


def is_staff(user) -> bool:
    return getattr(user, "role", None) in ("agent", "admin")


def is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin"


def create_project(user, key, name, method="scrum", **fields) -> Project:
    """Admin-only project creation, with the three default columns."""
    if not is_admin(user):
        raise PermissionDenied("Only admins can create projects.")
    project = Project(key=key, name=name, method=method, **fields)
    project.clean()
    project.save()
    for order, (column_name, category) in enumerate(DEFAULT_COLUMNS):
        Column.objects.create(project=project, name=column_name, category=category, order=order)
    return project


def create_issue(user, project, **fields) -> Issue:
    """Staff-only issue creation: next number, first to-do column, bottom of rank.

    The issue's own rules run before anything is written; the number is
    allocated under a row lock on the project.
    """
    if not is_staff(user):
        raise PermissionDenied("Only agents and admins can create issues.")
    fields.setdefault("column", _first_todo_column(project))
    if "rank" not in fields:
        fields["rank"] = _next_rank(project)
    Issue(project=project, reporter=user, **fields).clean()
    with transaction.atomic():
        locked = Project.objects.select_for_update().get(pk=project.pk)
        issue = Issue(project=locked, reporter=user, number=locked.next_number, **fields)
        issue.save()
        locked.next_number += 1
        locked.save(update_fields=["next_number"])
    _record(issue, "created", user, {"column": issue.column_id, "type": issue.type})
    return issue


def _first_todo_column(project):
    return project.columns.filter(category="todo").order_by("order", "id").first()


def _next_rank(project):
    top = Issue.objects.filter(project=project).order_by("-rank").values_list("rank", flat=True)
    highest = next(iter(top), None)
    return 0.0 if highest is None else highest + 1


def move_issue(user, issue, column, rank=None) -> Issue:
    """Move an issue to another column, freezing or unfreezing its cost."""
    if not is_staff(user):
        raise PermissionDenied("Only agents and admins can move issues.")
    from_column = issue.column
    if column is not None and column.project_id != issue.project_id:
        raise ValidationError("A column belongs to another project.")
    entering_done = column is not None and column.category == "done"
    reopening = not entering_done and from_column is not None and from_column.category == "done"
    if entering_done and issue.completed_at is None:
        issue.completed_at = timezone.now()

    issue.column = column
    if rank is not None:
        issue.rank = rank
    issue.save(update_fields=["column", "rank", "completed_at"])
    if entering_done:
        cost.freeze_cost(issue)
    elif reopening:
        _unfreeze(issue)
    _record(
        issue,
        "moved",
        user,
        {
            "from": from_column.id if from_column else None,
            "to": column.id if column else None,
            "from_category": from_column.category if from_column else "",
            "to_category": column.category if column else "",
        },
    )
    return issue


def _unfreeze(issue) -> None:
    """Reopening clears the freeze; the cost goes live again."""
    issue.completed_at = None
    issue.completed_by = None
    issue.frozen_cost = None
    issue.frozen_hours_per_point = None
    issue.save(
        update_fields=[
            "completed_at",
            "completed_by",
            "frozen_cost",
            "frozen_hours_per_point",
        ]
    )


def rank_between(issue, siblings, before) -> None:
    """Rank `issue` just above `before` in `siblings`, or last when None.

    `siblings` is the target list in display order (rank, number), without
    `issue`. Midpoint of the neighbours; when they are closer than
    RANK_EPSILON, renumber the whole list 1, 2, 3 … with `issue` in place.
    Saves the rank(s).
    """
    if before is None:
        issue.rank = (siblings[-1].rank if siblings else 0.0) + 1.0
        issue.save(update_fields=["rank"])
        return

    index = next(i for i, row in enumerate(siblings) if row.pk == before.pk)
    above = siblings[index].rank
    below = siblings[index - 1].rank if index > 0 else None
    if below is None:
        issue.rank = above - 1.0
        issue.save(update_fields=["rank"])
        return

    issue.rank = (below + above) / 2.0
    if above - below < RANK_EPSILON:
        _renumber(siblings, issue, index)
        return
    issue.save(update_fields=["rank"])


def _renumber(siblings, issue, index) -> None:
    """Spread a crowded list over 1, 2, 3 … with the moved issue in place."""
    ordered = siblings[:index] + [issue] + siblings[index:]
    Issue.objects.filter(pk__in=[row.pk for row in ordered]).update(
        rank=Case(
            *[
                When(pk=row.pk, then=float(position))
                for position, row in enumerate(ordered, start=1)
            ]
        )
    )


def set_sprint(user, issue, sprint_or_none) -> list[Issue]:
    """Put an issue in a sprint (or back to the backlog). Sub-tasks follow their parent."""
    if not is_staff(user):
        raise PermissionDenied("Only agents and admins can change sprints.")
    if sprint_or_none is not None and sprint_or_none.state == "closed":
        raise ValidationError("Cannot add issues to a closed sprint.")
    if issue.type == "subtask":
        raise ValidationError("Sub-tasks follow their parent into a sprint.")
    affected = [issue]
    for moved in affected + list(issue.children.filter(type="subtask")):
        _apply_sprint(moved, user, sprint_or_none)
    return affected


def _apply_sprint(issue, user, sprint):
    previous = issue.sprint
    issue.sprint = sprint
    issue.save(update_fields=["sprint"])
    if sprint is None:
        _record(issue, "sprint_removed", user, {"sprint": previous.id if previous else None})
    else:
        _record(issue, "sprint_added", user, {"sprint": sprint.id})


def set_points(user, issue, points) -> Issue:
    """Set story points. Sub-tasks carry none — they roll up into their parent."""
    if not is_staff(user):
        raise PermissionDenied("Only agents and admins can change points.")
    if issue.type == "subtask":
        raise ValidationError("Sub-tasks carry no points; they roll up into their parent.")
    previous = issue.story_points
    issue.story_points = points
    issue.save(update_fields=["story_points"])
    _record(issue, "points", user, {"from": previous, "to": points})
    return issue


def start_sprint(user, sprint, start_date, end_date) -> Sprint:
    """Start a sprint. One active sprint per project."""
    if not is_staff(user):
        raise PermissionDenied("Only agents and admins can start sprints.")
    active = Sprint.objects.filter(project=sprint.project, state="active").exclude(pk=sprint.pk)
    if active.exists():
        raise ValidationError("This project already has an active sprint.")
    if sprint.state == "closed":
        raise ValidationError("A closed sprint cannot be started.")
    sprint.state = "active"
    sprint.start_date = start_date
    sprint.end_date = end_date
    sprint.started_at = timezone.now()
    sprint.save(update_fields=["state", "start_date", "end_date", "started_at"])
    return sprint


def complete_sprint(user, sprint, move_open_to=None) -> Sprint:
    """Close a sprint; open work goes to `move_open_to` or back to the backlog."""
    if not is_staff(user):
        raise PermissionDenied("Only agents and admins can complete sprints.")
    if move_open_to is not None:
        if move_open_to.project_id != sprint.project_id:
            raise ValidationError("The next sprint belongs to another project.")
        if move_open_to.state == "closed":
            raise ValidationError("Open work cannot move into a closed sprint.")
    open_issues = list(sprint.issues.exclude(column__category="done"))
    now = timezone.now()
    sprint.state = "closed"
    sprint.closed_at = now
    sprint.save(update_fields=["state", "closed_at"])
    for issue in open_issues:
        _apply_sprint(issue, user, move_open_to)
    return sprint


def record_event(user, issue, kind, data) -> None:
    IssueEvent.objects.create(issue=issue, kind=kind, actor=user, data=data)


def _record(issue, kind, actor, data):
    record_event(actor, issue, kind, data)

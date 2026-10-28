"""Project metrics: burndown, velocity, cumulative flow and the cost breakdown.

Every function returns a widget-contract payload (validated before it leaves
here). The figures come from ``IssueEvent`` history rather than the issues as
they stand today: a day's number is the state at the *end* of that day.
"""

from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.dashboards.contract import validate_payload

from . import cost, permissions, views
from .models import Column, Issue, IssueEvent

CENT = Decimal("0.01")
DAY_END = time(23, 59, 59, 999999)

#: The columns that come out of the epic and sprint groupings; a person's table
#: cannot show a planned cost without showing that person's rates.
GROUP_COLUMNS = ["Name", "Points done", "Cost", "Planned cost", "Issues left out"]
PERSON_COLUMNS = ["Person", "Points done", "Cost", "Cost per point", "Issues left out"]


def burndown(sprint, today=None):
    """Points still open in this sprint, day by day, plus the ideal line."""
    today = timezone.localdate() if today is None else today
    labels = _day_range(sprint.start_date, sprint.end_date, today)

    replay = _SprintReplay(sprint)
    remaining = [replay.remaining(_end_of_day(day)) for day in labels]
    return _series(
        "line",
        [_iso(day) for day in labels],
        [("Remaining", remaining), ("Ideal", _ideal_line(remaining))],
    )


def velocity_chart(project, last=6):
    """Points committed against points completed, per closed sprint, oldest first."""
    sprints = _closed_sprints(project, last)
    return _series(
        "bar",
        [sprint.name for sprint in sprints],
        [
            ("Committed", [_committed(sprint) for sprint in sprints]),
            ("Completed", [_completed(sprint) for sprint in sprints]),
        ],
    )


def cumulative_flow(project, days=30, today=None):
    """How many issues sat in each column category, day by day."""
    today = timezone.localdate() if today is None else today
    labels = [today - timedelta(days=offset) for offset in range(max(days, 1) - 1, -1, -1)]
    replay = _FlowReplay(project)
    return _series(
        "line",
        [_iso(day) for day in labels],
        [
            (name, [replay.count(category, _end_of_day(day)) for day in labels])
            for category, name in (
                ("todo", "To do"),
                ("in_progress", "In progress"),
                ("done", "Done"),
            )
        ],
    )


def cost_breakdown(project, by, user):
    """The cost table: by person (admins), by epic, or by sprint."""
    if by not in ("person", "epic", "sprint"):
        raise ValueError(f"cost breakdown by {by!r} is not one of person/epic/sprint")
    if not permissions.can_see_cost(user):
        raise PermissionDenied("You may not see costs.")
    if by == "person" and not permissions.can_see_rates(user):
        raise PermissionDenied("Only admins may see cost per point.")

    if by == "person":
        columns, rows = PERSON_COLUMNS, _person_rows(project)
    elif by == "epic":
        columns, rows = GROUP_COLUMNS, _epic_rows(project)
    else:
        columns, rows = GROUP_COLUMNS, _sprint_rows(project)
    payload = {"columns": columns, "rows": rows}
    validate_payload("table", payload)
    return payload


class _SprintReplay:
    """Every issue that ever joined a sprint, and its open points at an instant."""

    def __init__(self, sprint):
        joined = IssueEvent.objects.filter(kind="sprint_added", data__sprint=sprint.pk)
        issues = Issue.objects.filter(
            pk__in=set(joined.values_list("issue_id", flat=True))
        ).exclude(type="subtask")
        self.items = _History.items(issues, sprint.pk)
        self.categories = _column_categories(self.items)

    def remaining(self, instant):
        return sum(
            item.size_at(instant)
            for item in self.items
            if item.in_scope_at(instant) and item.category_at(instant, self.categories) != "done"
        )


class _FlowReplay:
    """Which column category each of a project's issues sat in at an instant."""

    def __init__(self, project):
        self.items = _History.items(Issue.objects.filter(project=project).exclude(type="subtask"))
        self.categories = _column_categories(self.items)

    def count(self, category, instant):
        return sum(
            1
            for item in self.items
            if item.begins_by(instant) and item.category_at(instant, self.categories) == category
        )


class _History:
    """One issue's event trail, read as of any instant.

    Events are replayed in ``(created_at, id)`` order, so two events sharing an
    instant keep the order they were written in.
    """

    def __init__(self, issue, events, sprint_id=None):
        self.issue = issue
        self.events = events
        self.sprint_id = sprint_id

    @classmethod
    def items(cls, issues, sprint_id=None):
        """One history per issue, with that issue's events loaded."""
        issues = list(issues)
        events = {}
        for event in IssueEvent.objects.filter(issue__in=issues).order_by("created_at", "id"):
            events.setdefault(event.issue_id, []).append(event)
        return [cls(issue, events.get(issue.pk, []), sprint_id) for issue in issues]

    def _until(self, instant, *kinds):
        return [e for e in self.events if e.kind in kinds and e.created_at <= instant]

    def begins_by(self, instant):
        return bool(self._until(instant, "created"))

    def start_column_id(self):
        created = next((e for e in self.events if e.kind == "created"), None)
        return None if created is None else (created.data or {}).get("column")

    def in_scope_at(self, instant):
        """In this sprint from a join naming it, out after leaving it or joining another."""
        inside = False
        for event in self._until(instant, "sprint_added", "sprint_removed"):
            named = (event.data or {}).get("sprint")
            if event.kind == "sprint_added":
                inside = named == self.sprint_id
            elif named == self.sprint_id:
                inside = False
        return inside

    def category_at(self, instant, categories):
        """The created column's category (To do when unknown), then each move's."""
        category = categories.get(self.start_column_id(), "todo")
        for event in self._until(instant, "moved"):
            category = (event.data or {}).get("to_category") or category
        return category

    def size_at(self, instant):
        """The latest re-estimate by then; before any, what the first one changed
        from; with none at all, today's points. Unsized counts as 0."""
        changes = [e for e in self.events if e.kind == "points"]
        before = [e for e in changes if e.created_at <= instant]
        if before:
            size = (before[-1].data or {}).get("to")
        elif changes:
            size = (changes[0].data or {}).get("from")
        else:
            size = self.issue.story_points
        return size or 0


def _closed_sprints(project, last):
    """The ``last`` most recently closed sprints, oldest first."""
    sprints = list(
        project.sprints.filter(state="closed", closed_at__isnull=False).order_by(
            "-closed_at", "-id"
        )[:last]
    )
    sprints.reverse()
    return sprints


def _committed(sprint):
    """Points in scope when the sprint started; a sprint that never started uses
    the issues it holds today."""
    if sprint.started_at is None:
        return sum(
            issue.story_points or 0
            for issue in sprint.issues.exclude(type="subtask").select_related("column")
        )
    replay = _SprintReplay(sprint)
    return sum(
        item.size_at(sprint.started_at)
        for item in replay.items
        if item.in_scope_at(sprint.started_at)
    )


def _completed(sprint):
    issues = sprint.issues.exclude(type="subtask").filter(completed_at__lt=sprint.closed_at)
    if sprint.started_at is not None:
        issues = issues.filter(completed_at__gte=sprint.started_at)
    return sum(issue.story_points or 0 for issue in issues)


def _person_rows(project):
    groups = {}
    for issue in _done_issues(project):
        groups.setdefault(issue.completed_by or issue.assignee, []).append(issue)
    return [
        _person_row(views.display_name(person), groups[person])
        for person in sorted(groups, key=_person_key)
    ]


def _epic_rows(project):
    issues = _breakdown_issues(project)
    children = _children_by_parent(issues)
    rows = []
    for epic in project.issues.filter(type="epic").order_by("number"):
        descendants = _descendants(epic.pk, children)
        if descendants:
            rows.append(_group_row(epic.title, descendants))
    orphans = [issue for issue in issues if not _under_an_epic(issue)]
    if orphans:
        rows.append(_group_row("No epic", orphans))
    return rows


def _sprint_rows(project):
    groups = {}
    backlog = []
    for issue in _breakdown_issues(project):
        if issue.sprint_id is None:
            backlog.append(issue)
        else:
            groups.setdefault(issue.sprint_id, []).append(issue)
    sprints = project.sprints.filter(pk__in=groups).order_by("-closed_at", "-id")
    rows = [_group_row(sprint.name, groups[sprint.pk]) for sprint in sprints]
    if backlog:
        rows.append(_group_row("Backlog", backlog))
    return rows


def _person_row(name, issues):
    points = _points(issues)
    total, left_out = cost.total_cost(issues)
    return [name, points, _money(total), _per_point(total, points), left_out]


def _group_row(name, issues):
    done = [issue for issue in issues if issue.is_done]
    total, left_out = cost.total_cost(done)
    return [name, _points(done), _money(total), _money(_planned_cost(issues)), left_out]


def _under_an_epic(issue):
    """Whether the issue hangs under an epic: its parent is one, or its
    grandparent is — nothing sits three levels below an epic."""
    if issue.parent_id is None:
        return False
    parent = issue.parent
    return parent.type == "epic" or (parent.parent_id is not None and parent.parent.type == "epic")


def _children_by_parent(issues):
    children = {}
    for issue in issues:
        children.setdefault(issue.parent_id, []).append(issue)
    return children


def _descendants(epic_id, children):
    found = []
    queue = list(children.get(epic_id, []))
    while queue:
        issue = queue.pop()
        found.append(issue)
        queue.extend(children.get(issue.pk, []))
    return found


def _breakdown_issues(project):
    return list(
        Issue.objects.filter(project=project)
        .exclude(type="epic")
        .select_related("column", "sprint", "parent", "assignee", "completed_by")
    )


def _done_issues(project):
    return list(
        Issue.objects.filter(project=project, column__category="done")
        .exclude(type="subtask")
        .select_related("column", "assignee", "completed_by")
    )


def _column_categories(items):
    ids = {item.start_column_id() for item in items}
    ids.discard(None)
    return dict(Column.objects.filter(pk__in=ids).values_list("pk", "category"))


def _points(issues):
    return sum(issue.story_points or 0 for issue in issues)


def _planned_cost(issues):
    total = Decimal("0")
    for issue in issues:
        estimate = cost.estimate_cost(issue)
        if estimate is not None:
            total += estimate
    return total


def _per_point(total, points):
    if not points:
        return "—"
    return _money(total / Decimal(points))


def _money(value):
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):.2f}"


def _person_key(person):
    return (person is None, views.display_name(person))


def _ideal_line(remaining):
    count = len(remaining)
    if count <= 1:
        return list(remaining)
    first = remaining[0]
    return [(first * (count - 1 - index)) // (count - 1) for index in range(count)]


def _day_range(start, end, today):
    if start is None:
        return []
    last = today if end is None else min(end, today)
    return [start + timedelta(days=offset) for offset in range((last - start).days + 1)]


def _end_of_day(day):
    return timezone.make_aware(datetime.combine(day, DAY_END))


def _iso(day):
    return day.isoformat()


def _series(kind, labels, series):
    payload = {
        "kind": kind,
        "labels": labels,
        "series": [{"name": name, "values": values} for name, values in series],
    }
    validate_payload("series", payload)
    return payload

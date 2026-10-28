"""Cost: who is worth an hour, what a point is worth, and what an issue costs.

Money is Decimal throughout; every missing input returns ``None`` so the caller
can show "not set" and leave the figure out of totals.
"""

from decimal import ROUND_HALF_UP, Decimal

from .models import CostSettings, Issue, Sprint

#: How many of a person's closed sprints their velocity averages over.
HISTORY_SPRINTS = 3

CENT = Decimal("0.01")


def velocity(user, project=None, as_of=None):
    """Average story points `user` completed per closed sprint.

    Averages over the last HISTORY_SPRINTS closed sprints that had completed
    work by them. None until that much history exists.
    """
    if user is None:
        return None
    sprints = list(_completed_sprints(user, project=project, as_of=as_of))
    if len(sprints) < HISTORY_SPRINTS:
        return None
    total = sum(_points_in(sprint, user) for sprint in sprints)
    return Decimal(total) / Decimal(HISTORY_SPRINTS)


def hours_per_point(user, as_of=None):
    """`sprint_hours` ÷ velocity, else the org-wide default.

    Velocity is the average over their last three closed sprints of work they
    completed; without it, or with it at zero, there is nothing to divide by
    and the admin's default stands. No division by zero on any path.
    """
    points_per_sprint = velocity(user, as_of=as_of)
    rate = _rate(user)
    if (
        points_per_sprint is not None
        and points_per_sprint > 0
        and rate is not None
        and rate.sprint_hours is not None
    ):
        return rate.sprint_hours / points_per_sprint
    return CostSettings.get_solo().default_hours_per_point


def rate_for(user):
    """What an hour of this person costs; None when no wage is set."""
    rate = _rate(user)
    if rate is None:
        return None
    return rate.hourly_wage


def issue_cost(issue):
    """The frozen cost of a done issue, else a live estimate, at whole cents.

    None when the estimate has nothing to stand on — no points, no assignee,
    or an assignee with no wage or no hours-per-point.
    """
    if issue.column_id is not None and issue.column.category == "done":
        return None if issue.frozen_cost is None else _quantise(issue.frozen_cost)
    return estimate_cost(issue)


def estimate_cost(issue):
    """Points × hours per point × wage, quantised.

    None when the assignee's cost is "not set" — no wage at all — or the
    issue has no points or no assignee. Hours per point always has a value
    (the org default covers someone without history).
    """
    if issue.story_points is None or issue.assignee_id is None:
        return None
    wage = rate_for(issue.assignee)
    if wage is None:
        return None
    hours = hours_per_point(issue.assignee)
    return _quantise(Decimal(issue.story_points) * hours * wage)


def freeze_cost(issue) -> None:
    """Freeze the cost on a done issue, saving the frozen fields.

    ``completed_by`` is the assignee at this moment, so a later reassignment
    cannot rewrite history. The frozen figures stay None when the inputs are
    missing — the issue then contributes nothing to totals.
    """
    issue.completed_by = issue.assignee
    issue.frozen_hours_per_point = hours_per_point(issue.assignee) if issue.assignee else None
    issue.frozen_cost = estimate_cost(issue)
    issue.save(update_fields=["completed_by", "frozen_cost", "frozen_hours_per_point"])


def rollup_points(issue) -> int:
    """An issue's own points. Sub-tasks carry none, so nothing rolls up."""
    return issue.story_points or 0


def total_cost(issues):
    """(sum of the known costs, how many issues were left out). Both in cents."""
    total = Decimal("0")
    missing = 0
    for issue in issues:
        cost = issue_cost(issue)
        if cost is None:
            missing += 1
        else:
            total += _quantise(cost)
    return _quantise(total), missing


def _quantise(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _rate(user):
    from .models import PersonRate

    if user is None:
        return None
    return PersonRate.objects.filter(user=user).first()


def _completed_sprints(user, project=None, as_of=None):
    """Closed sprints with completed work by `user`, most recently closed first."""
    sprints = Sprint.objects.filter(state="closed", closed_at__isnull=False)
    if project is not None:
        sprints = sprints.filter(project=project)
    if as_of is not None:
        sprints = sprints.filter(closed_at__lte=as_of)
    for sprint in sprints.order_by("-closed_at", "-id"):
        if _issues_completed_in(sprint, user).exists():
            yield sprint


def _issues_completed_in(sprint, user):
    """Work by `user` completed between the sprint's start and its close.

    An unplanned sprint has no started_at; its whole life is then the window.
    """
    issues = Issue.objects.filter(
        sprint=sprint, completed_by=user, completed_at__lt=sprint.closed_at
    )
    if sprint.started_at is None:
        return issues
    return issues.filter(completed_at__gte=sprint.started_at)


def _points_in(sprint, user):
    return sum(issue.story_points or 0 for issue in _issues_completed_in(sprint, user))

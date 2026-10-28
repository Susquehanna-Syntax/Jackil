"""The ``card`` and ``project`` link types."""

import re

from django.urls import reverse

from apps.links.registry import LinkTarget, Resolver, register_type

from .permissions import can_see_projects

#: A path ending /projects/<KEY>-<n>/ or /projects/<KEY>/, with or without a host.
_ISSUE_URL = re.compile(r"(?:^|/)projects/([A-Za-z][A-Za-z0-9]{1,9}-[0-9]+)/?$")
_PROJECT_URL = re.compile(r"(?:^|/)projects/([A-Za-z][A-Za-z0-9]{1,9})/?$")

_ISSUE_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9]{1,9})-([0-9]+)$")


class IssueResolver(Resolver):
    """Ids may be a pk or the issue's own ``KEY-n``; each comes back under the
    id it was asked for, so a wiki ``[[card:NET-12]]`` keeps working."""

    def resolve(self, ids: list[str], user) -> dict[str, LinkTarget]:
        if not can_see_projects(user):
            return {}
        from .models import Issue

        issues = Issue.objects.select_related("project", "column")
        targets = {
            str(issue.pk): _issue_target(issue)
            for issue in issues.filter(pk__in=[int(i) for i in ids if i.isdigit()])
        }
        for raw in ids:
            match = _ISSUE_KEY.match(raw)
            if match is None:
                continue
            issue = issues.filter(
                project__key=match.group(1).upper(), number=int(match.group(2))
            ).first()
            if issue is not None:
                targets[raw] = _issue_target(issue)
        return targets

    def search(self, q: str, user, limit: int) -> list[LinkTarget]:
        if not can_see_projects(user):
            return []
        from .models import Issue

        term = q.strip()
        if not term:
            return []
        issues = Issue.objects.select_related("project", "column")
        match = _ISSUE_KEY.match(term)
        if match:
            issues = issues.filter(project__key=match.group(1).upper(), number=int(match.group(2)))
        else:
            issues = issues.filter(title__icontains=term)
        return [_issue_target(issue) for issue in issues[:limit]]

    def from_url(self, url: str) -> str | None:
        match = _ISSUE_URL.search(url)
        if match is None:
            return None
        from .models import Issue

        key, _, number = match.group(1).rpartition("-")
        pk = (
            Issue.objects.filter(project__key=key.upper(), number=int(number))
            .values_list("pk", flat=True)
            .first()
        )
        return None if pk is None else str(pk)


class ProjectResolver(Resolver):
    def resolve(self, ids: list[str], user) -> dict[str, LinkTarget]:
        if not can_see_projects(user):
            return {}
        from .models import Project

        numeric = [int(i) for i in ids if i.isdigit()]
        return {
            str(project.pk): _project_target(project)
            for project in Project.objects.filter(pk__in=numeric)
        }

    def search(self, q: str, user, limit: int) -> list[LinkTarget]:
        if not can_see_projects(user):
            return []
        from .models import Project

        term = q.strip()
        if not term:
            return []
        projects = Project.objects.filter(key__istartswith=term) | Project.objects.filter(
            name__icontains=term
        )
        return [_project_target(project) for project in projects[:limit]]

    def from_url(self, url: str) -> str | None:
        match = _PROJECT_URL.search(url)
        if match is None or "-" in match.group(1):
            return None
        from .models import Project

        pk = Project.objects.filter(key=match.group(1).upper()).values_list("pk", flat=True).first()
        return None if pk is None else str(pk)


def _issue_target(issue) -> LinkTarget:
    done = issue.column is not None and issue.column.category == "done"
    return LinkTarget(
        type="card",
        id=str(issue.pk),
        label=f"{issue.key} {issue.title}",
        url=reverse("projects:issue_detail", args=[(issue.project.key, issue.number)]),
        status=issue.column.name if issue.column else "",
        tone="ok" if done else "info",
    )


def _project_target(project) -> LinkTarget:
    return LinkTarget(
        type="project",
        id=str(project.pk),
        label=f"{project.key} {project.name}",
        url=reverse("projects:project_detail", args=[project.key]),
        status=project.get_method_display(),
        tone="info",
    )


def register_project_types() -> None:
    register_type("card", IssueResolver())
    register_type("project", ProjectResolver())

"""The header every project screen shares: name, key, a line of facts, and
the Board / Reports / Settings tabs (UX pass M15)."""

from django.urls import reverse

from . import permissions
from .models import Issue

SHELL_TABS = (
    ("board", "Board", "sky", "projects:board"),
    ("reports", "Reports", "lav", "projects:reports"),
    ("settings", "Settings", "peach", "projects:project_settings"),
)


def project_shell(request, project, active: str) -> dict:
    """Context for templates/projects/_shell.html. Settings is listed only
    for those who may change it."""
    can_admin = permissions.can_admin_projects(request.user)
    tabs = []
    for name, label, colour, url_name in SHELL_TABS:
        if name == "settings" and not can_admin:
            continue
        tabs.append(
            {
                "label": label,
                "colour": colour,
                "url": reverse(url_name, args=[project.key]),
                "active": name == active,
            }
        )
    open_issues = (
        Issue.objects.filter(project=project)
        .exclude(column__category="done")
        .exclude(type="subtask")
        .count()
    )
    return {
        "shell_tabs": tabs,
        "shell_open": open_issues,
        "shell_active": active,
        "can_admin": can_admin,
    }

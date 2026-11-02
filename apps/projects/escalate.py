"""Escalating a helpdesk ticket into planned project work."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.links.service import add_link
from apps.projects.permissions import can_see_projects
from apps.tickets.permissions import can_view_ticket
from apps.tickets.services import record_system_event

from . import service
from .models import Issue, Project
from .views import issue_url

ISSUE_TYPES = ("story", "task", "bug")


@login_required
@require_POST
def escalate(request, ticket_pk):
    """Turn a ticket into an issue, link both ends, and note the ticket."""
    from apps.tickets.models import Ticket

    if not can_see_projects(request.user):
        raise PermissionDenied
    ticket = get_object_or_404(Ticket, pk=ticket_pk)
    if not can_view_ticket(request.user, ticket):
        raise PermissionDenied

    project_key = request.POST.get("project", "")
    issue_type = request.POST.get("type", "")
    if issue_type not in ISSUE_TYPES:
        issue_type = "task"
    title = request.POST.get("title", "").strip() or ticket.title
    title = title[: Issue._meta.get_field("title").max_length]

    project = Project.objects.filter(key=project_key, is_archived=False).first()
    if project is None:
        messages.error(request, "Pick a project.")
        return redirect("tickets:ticket_detail", pk=ticket.pk)

    quote = "\n".join(f"> {line}" for line in ticket.description.splitlines())
    description = f"Escalated from ticket #{ticket.pk}." + (f"\n\n{quote}" if quote else "")

    with transaction.atomic():
        issue = service.create_issue(
            request.user, project, title=title, type=issue_type, description=description
        )
        add_link(request.user, ("ticket", str(ticket.pk)), ("card", str(issue.pk)), "fixed_by")
        record_system_event(ticket, request.user, f"Escalated to {issue.key}")

    messages.success(request, f"Created {issue.key} from ticket #{ticket.pk}.")
    return redirect(issue_url(issue))

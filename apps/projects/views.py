"""Projects pages: the list, project issue lists, issues and their comments."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.ui.live import render_live
from apps.wiki.markdown import render as render_markdown

from . import permissions, service
from .cost import issue_cost
from .forms import ColumnForm, IssueForm, ProjectForm
from .models import Column, CostSettings, Issue, IssueComment, Project, Sprint
from .shell import project_shell

#: Pill tint per issue type, on the design language's colour names.
TYPE_TONE = {
    "epic": "tc-lav",
    "story": "tc-sky",
    "task": "tc-mint",
    "bug": "tc-rose",
    "subtask": "tc-peach",
}

#: Pill tint per priority.
PRIORITY_TONE = {
    "critical": "tc-rose",
    "high": "tc-peach",
    "medium": "tc-sky",
    "low": "tc-mint",
}


def display_name(person) -> str:
    """The name every Projects page shows for a colleague."""
    if person is None:
        return "—"
    return person.get_full_name() or person.username


@login_required
def project_list(request):
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    show_archived = request.GET.get("archived") == "1"
    projects = Project.objects.select_related("lead", "department")
    projects = (
        projects.filter(is_archived=True) if show_archived else projects.filter(is_archived=False)
    )
    open_counts = dict(
        Issue.objects.exclude(column__category="done")
        .values("project__key")
        .annotate(n=Count("id"))
        .values_list("project__key", "n")
    )
    ctx = {
        "projects": projects,
        "cards": [
            {
                "project": project,
                "lead": display_name(project.lead),
                "method": project.get_method_display(),
                "open": open_counts.get(project.key, 0),
            }
            for project in projects
        ],
        "show_archived": show_archived,
        "can_admin": permissions.can_admin_projects(request.user),
    }
    return render(request, "projects/project_list.html", ctx)


@login_required
def project_create(request):
    if not permissions.can_admin_projects(request.user):
        raise PermissionDenied
    form = ProjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        project = service.create_project(
            request.user,
            key=data["key"],
            name=data["name"],
            method=data["method"],
            lead=data.get("lead"),
            department=data.get("department"),
            description=data["description"],
        )
        if data["is_archived"]:
            Project.objects.filter(pk=project.pk).update(is_archived=True)
        messages.success(request, f"Project “{project.key}” created.")
        return redirect("projects:project_detail", key=project.key)
    return render(
        request,
        "projects/project_form.html",
        {"form": form, "title": "New project", "submit_label": "Create project"},
    )


@login_required
def project_settings(request, key):
    if not permissions.can_admin_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())
    new_column_form = ColumnForm()
    form = ProjectForm(instance=project)
    if request.method == "POST":
        posted = request.POST
        if posted.get("action") != "columns":
            form = ProjectForm(posted, instance=project)
            if form.is_valid():
                form.save()
                messages.success(request, f"Project “{project.key}” updated.")
                return redirect("projects:project_detail", key=project.key)
        elif posted.get("add_column"):
            new_column_form = ColumnForm(posted)
            _add_column(request, project, new_column_form)
        elif posted.get("delete_column"):
            _delete_column(request, project)
        else:
            _save_columns(request, project)
        if not (new_column_form.is_bound and not new_column_form.is_valid()):
            return redirect("projects:project_settings", key=project.key)
    return render(
        request,
        "projects/project_settings.html",
        {
            "project": project,
            "form": form,
            "column_rows": _column_rows(project),
            "new_column_form": new_column_form,
            **project_shell(request, project, "settings"),
        },
    )


def _add_column(request, project, added) -> None:
    if not added.is_valid():
        messages.error(request, "That column could not be added.")
        return
    column = added.save(commit=False)
    column.project = project
    highest = project.columns.order_by("-order").values_list("order", flat=True).first()
    column.order = 0 if highest is None else highest + 1
    column.save()
    messages.success(request, f"Column “{column.name}” added.")


def _column_rows(project):
    """One row per column, with its issue count and the names it may become."""
    return [
        {
            "column": column,
            "issues": column.issues.count(),
            "categories": Column.CATEGORY_CHOICES,
        }
        for column in project.columns.all()
    ]


def _delete_column(request, project) -> None:
    column = get_object_or_404(Column, pk=request.POST["delete_column"], project=project)
    if column.issues.exists():
        messages.error(request, f"“{column.name}” still has issues. Move them first.")
    else:
        column.delete()
        messages.success(request, f"Column “{column.name}” deleted.")


def _save_columns(request, project) -> None:
    """Rename, reorder and re-categorise the columns that came back."""
    for column in project.columns.all():
        edited = ColumnForm(
            {
                "name": request.POST.get(f"name-{column.pk}", column.name),
                "category": request.POST.get(f"category-{column.pk}", column.category),
                "order": request.POST.get(f"order-{column.pk}", column.order),
                "wip_limit": request.POST.get(f"wip-limit-{column.pk}", ""),
            },
            instance=column,
        )
        if edited.is_valid():
            edited.save()
    messages.success(request, "Columns updated.")


@login_required
def project_detail(request, key):
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())
    issues = project.issues.select_related("column", "assignee", "sprint")

    issue_type = request.GET.get("type", "").strip()
    assignee = request.GET.get("assignee", "").strip()
    status = request.GET.get("status", "").strip()
    query = request.GET.get("q", "").strip()
    if issue_type:
        issues = issues.filter(type=issue_type)
    if assignee == "me":
        issues = issues.filter(assignee=request.user)
    elif assignee == "none":
        issues = issues.filter(assignee__isnull=True)
    elif assignee.isdigit():
        issues = issues.filter(assignee_id=int(assignee))
    if status:
        issues = issues.filter(column__category=status)
    if query:
        issues = issues.filter(title__icontains=query)

    ctx = {
        "project": project,
        "issues": [
            {
                "issue": issue,
                "key": issue.key,
                "url": issue_url(issue),
                "assignee": display_name(issue.assignee),
                "type_tone": TYPE_TONE.get(issue.type, "tc-sky"),
                "priority_tone": PRIORITY_TONE.get(issue.priority, "tc-sky"),
                "type": issue.get_type_display(),
                "priority": issue.get_priority_display(),
            }
            for issue in issues
        ],
        "issue_count": issues.count(),
        "issue_type": issue_type,
        "assignee": assignee,
        "status": status,
        "query": query,
        "statuses": Column.CATEGORY_CHOICES,
        "types": Issue.TYPE_CHOICES,
        "staff": permissions.staff_users(),
        "can_see_cost": permissions.can_see_cost(request.user),
        **project_shell(request, project, "board"),
    }
    return render_live(request, "projects/project_detail.html", "projects/_issue_results.html", ctx)


@login_required
def issue_create(request, key):
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    project = get_object_or_404(Project, key=key.upper())
    form = IssueForm(request.POST or None, project=project, initial=_create_initial(request))
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        issue = service.create_issue(
            request.user,
            project,
            type=data["type"],
            title=data["title"],
            description=data["description"],
            parent=data.get("parent"),
            assignee=data.get("assignee"),
            priority=data["priority"],
            labels=data["labels"],
            story_points=data.get("story_points"),
        )
        if data.get("sprint") is not None:
            service.set_sprint(request.user, issue, data["sprint"])
        messages.success(request, f"Issue {issue.key} created.")
        return redirect("projects:issue_detail", ref=(project.key, issue.number))
    return render(
        request,
        "projects/issue_form.html",
        {
            "project": project,
            "form": form,
            "title": f"New issue in {project.key}",
            "submit_label": "Create issue",
            "is_subtask": form.issue_type == "subtask",
        },
    )


def _create_initial(request):
    initial = {}
    issue_type = request.GET.get("type", "").strip()
    if issue_type in dict(Issue.TYPE_CHOICES):
        initial["type"] = issue_type
    parent_key = request.GET.get("parent", "").strip().upper()
    prefix, dash, number = parent_key.rpartition("-")
    if dash and number.isdigit():
        parent = Issue.objects.filter(project__key=prefix, number=int(number)).first()
        if parent is not None:
            initial["parent"] = parent.pk
    return initial


@login_required
def issue_detail(request, ref):
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    key, number = ref
    issue = get_object_or_404(
        Issue.objects.select_related(
            "project", "column", "assignee", "reporter", "sprint", "parent"
        ),
        project__key=key.upper(),
        number=number,
    )
    children = list(issue.children.select_related("column").order_by("number"))
    events = list(issue.events.select_related("actor").order_by("-created_at", "-id")[:40])
    ctx = {
        "issue": issue,
        "issue_url": issue_url(issue),
        "edit_url": sub_url(issue, "issue_edit"),
        "move_url": sub_url(issue, "issue_move"),
        "comment_url": sub_url(issue, "issue_comment"),
        "parent_url": issue_url(issue.parent) if issue.parent else "",
        "is_done": issue.is_done,
        "description_html": render_markdown(issue.description, user=request.user),
        "type_tone": TYPE_TONE.get(issue.type, "tc-sky"),
        "priority_tone": PRIORITY_TONE.get(issue.priority, "tc-sky"),
        "assignee": display_name(issue.assignee),
        "reporter": display_name(issue.reporter),
        "labels": _labels(issue),
        "children": [
            {"issue": child, "key": child.key, "url": issue_url(child)} for child in children
        ],
        "is_epic": issue.type == "epic",
        "epic_points": sum(child.story_points or 0 for child in children),
        "epic_done": sum(1 for child in children if child.is_done),
        "comments": [
            {
                "author": display_name(comment.author),
                "created_at": comment.created_at,
                "body_html": render_markdown(comment.body, user=request.user),
            }
            for comment in issue.comments.select_related("author")
        ],
        "events": [
            {
                "event": event,
                "actor": display_name(event.actor),
                "line": _event_line(event),
            }
            for event in events
        ],
        "columns": list(project_columns(issue.project)),
        "can_see_cost": permissions.can_see_cost(request.user),
        "cost": _cost_text(issue),
    }
    return render(request, "projects/issue_detail.html", ctx)


def project_columns(project):
    return project.columns.all()


@login_required
def issue_edit(request, ref):
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    key, number = ref
    issue = get_object_or_404(
        Issue.objects.select_related("project"), project__key=key.upper(), number=number
    )
    project = issue.project
    points_before = issue.story_points
    sprint_before = issue.sprint_id
    assignee_before = issue.assignee_id
    was_subtask = issue.type == "subtask"
    # The form gets its own copy: validating writes the posted values onto its
    # instance, and the service must see the old points and sprint to record
    # what changed.
    form = IssueForm(request.POST or None, instance=Issue.objects.get(pk=issue.pk), project=project)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        for field in ("type", "title", "description", "priority", "labels", "parent"):
            setattr(issue, field, data[field])
        issue.save()
        _apply_changes(
            request, issue, data, points_before, sprint_before, assignee_before, was_subtask
        )
        messages.success(request, f"Issue {issue.key} updated.")
        return redirect("projects:issue_detail", ref=(project.key, issue.number))
    return render(
        request,
        "projects/issue_form.html",
        {
            "project": project,
            "issue": issue,
            "form": form,
            "title": f"Edit {issue.key}",
            "submit_label": "Save changes",
            "is_subtask": form.issue_type == "subtask",
        },
    )


def _apply_changes(
    request, issue, data, points_before, sprint_before, assignee_before, was_subtask
):
    """Points and sprint go through the service so the trail keeps them."""
    sprint = data.get("sprint")
    points = data.get("story_points")
    if was_subtask:
        # The form carries neither for a sub-task, so nothing here can change them.
        sprint = Sprint.objects.filter(pk=sprint_before).first()
        points = points_before
    else:
        if points != points_before:
            service.set_points(request.user, issue, points)
        if (sprint.pk if sprint else None) != sprint_before:
            service.set_sprint(request.user, issue, sprint)
    assignee = data.get("assignee")
    assignee_pk = assignee.pk if assignee else None
    if assignee_pk != assignee_before:
        issue.assignee = assignee
        issue.save(update_fields=["assignee"])
        service.record_event(request.user, issue, "assigned", {"assignee": assignee_pk})


@login_required
def issue_move(request, ref):
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    key, number = ref
    issue = get_object_or_404(
        Issue.objects.select_related("project"), project__key=key.upper(), number=number
    )
    if request.method == "POST":
        posted = request.POST.get("column", "").strip()
        target = (
            Column.objects.filter(pk=posted, project=issue.project).first()
            if posted.isdigit()
            else None
        )
        if target is None:
            messages.error(request, "Pick a column in this project.")
        else:
            service.move_issue(request.user, issue, target)
            messages.success(request, f"{issue.key} moved to {target.name}.")
    return redirect("projects:issue_detail", ref=(issue.project.key, issue.number))


@login_required
def issue_comment(request, ref):
    if not permissions.can_see_projects(request.user):
        raise PermissionDenied
    key, number = ref
    issue = get_object_or_404(
        Issue.objects.select_related("project"), project__key=key.upper(), number=number
    )
    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if body:
            IssueComment.objects.create(issue=issue, author=request.user, body=body)
        else:
            messages.error(request, "Write something first.")
    return redirect("projects:issue_detail", ref=(issue.project.key, issue.number))


def sub_url(issue, name) -> str:
    """An issue's action URL: /projects/NET-12/edit/, ..."""
    return reverse(f"projects:{name}", args=[(issue.project.key, issue.number)])


def issue_url(issue) -> str:
    return reverse("projects:issue_detail", args=[(issue.project.key, issue.number)])


def _labels(issue) -> list[str]:
    return [label.strip() for label in (issue.labels or "").split(",") if label.strip()]


def _cost_text(issue) -> str:
    cost = issue_cost(issue)
    return "not set" if cost is None else f"{CostSettings.get_solo().currency} {cost}"


def _event_line(event) -> str:
    """One event in plain words, for the activity list."""
    data = event.data or {}
    if event.kind == "created":
        return "Created"
    if event.kind == "moved":
        name = Column.objects.filter(pk=data.get("to")).values_list("name", flat=True).first()
        return f"Moved to {name}" if name else "Moved"
    if event.kind == "sprint_added":
        name = Sprint.objects.filter(pk=data.get("sprint")).values_list("name", flat=True).first()
        return f"Added to {name}" if name else "Added to a sprint"
    if event.kind == "sprint_removed":
        return "Removed from the sprint"
    if event.kind == "points":
        return f"Points {_points_shown(data.get('from'))} → {_points_shown(data.get('to'))}"
    if event.kind == "assigned":
        return "Assigned"
    return "Edited"


def _points_shown(value) -> str:
    return "—" if value is None else str(value)

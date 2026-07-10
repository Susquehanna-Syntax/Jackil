from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.models import Department, User

from . import permissions
from .models import Attachment, Ticket
from .services import AttachmentTooLarge, post_message, record_system_event


def dashboard(request):
    if not request.user.is_authenticated:
        return render(request, "tickets/dashboard_public.html")
    if request.user.role == "customer":
        return redirect("tickets:customer_tickets")
    return dashboard_auth(request)


@login_required
def dashboard_auth(request):
    total = Ticket.objects.count()
    open_tickets = Ticket.objects.filter(status="open")
    my_open = open_tickets.filter(assigned_to=request.user).count()
    open_total = open_tickets.count()
    in_progress = Ticket.objects.filter(status="in_progress").count()
    resolved = Ticket.objects.filter(status="resolved").count()
    closed = Ticket.objects.filter(status="closed").count()
    critical = Ticket.objects.filter(
        priority="critical", status__in=["open", "in_progress"]
    ).count()
    recent = Ticket.objects.select_related(
        "created_by", "assigned_to", "department"
    ).prefetch_related("assigned_users")[:8]
    my_tickets = (
        Ticket.objects.filter(assigned_to=request.user)
        .select_related("created_by", "assigned_to", "department")
        .prefetch_related("assigned_users")[:5]
    )
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    this_week = Ticket.objects.filter(created_at__date__gte=week_ago).count()

    now = timezone.now()
    open_states = ["open", "in_progress", "pending"]
    overdue_tickets = (
        Ticket.objects.filter(status__in=open_states, resolution_due__lt=now)
        .select_related("created_by", "assigned_to")
        .order_by("resolution_due")[:6]
    )
    sla_overdue = Ticket.objects.filter(status__in=open_states, resolution_due__lt=now).count()
    sla_breached = (
        Ticket.objects.filter(status__in=open_states)
        .filter(Q(response_breached=True) | Q(resolution_breached=True))
        .count()
    )

    ctx = {
        "total": total,
        "my_open": my_open,
        "open_total": open_total,
        "in_progress": in_progress,
        "resolved": resolved,
        "closed": closed,
        "critical": critical,
        "recent": recent,
        "my_tickets": my_tickets,
        "this_week": this_week,
        "overdue_tickets": overdue_tickets,
        "sla_overdue": sla_overdue,
        "sla_breached": sla_breached,
        "show_needs_attention": (request.user.preferences or {}).get("show_needs_attention", True),
    }
    return render(request, "tickets/dashboard.html", ctx)


@login_required
def customer_tickets(request):
    tickets = (
        Ticket.objects.filter(created_by=request.user)
        .select_related("assigned_to", "department")
        .prefetch_related("assigned_users")
        .order_by("-created_at")
    )

    status = request.GET.get("status")
    search = request.GET.get("search", "").strip()

    if status:
        tickets = tickets.filter(status=status)
    if search:
        tickets = tickets.filter(Q(title__icontains=search) | Q(description__icontains=search))

    ctx = {
        "tickets": tickets,
        "status": status,
        "search": search,
    }
    return render(request, "tickets/customer_tickets.html", ctx)


@login_required
def ticket_list(request):
    if request.user.role == "customer":
        return customer_tickets(request)

    tickets = Ticket.objects.select_related(
        "created_by", "assigned_to", "department"
    ).prefetch_related("assigned_users")

    status = request.GET.get("status")
    priority = request.GET.get("priority")
    assigned = request.GET.get("assigned")
    search = request.GET.get("search", "").strip()

    if status:
        tickets = tickets.filter(status=status)
    if priority:
        tickets = tickets.filter(priority=priority)
    if assigned == "mine":
        tickets = tickets.filter(assigned_to=request.user)
    elif assigned == "unassigned":
        tickets = tickets.filter(assigned_to__isnull=True)
    if search:
        tickets = tickets.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(tags__icontains=search)
        )

    tickets = tickets[:50]

    ctx = {
        "tickets": tickets,
        "status": status,
        "priority": priority,
        "assigned": assigned,
        "search": search,
    }
    return render(request, "tickets/list.html", ctx)


@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)

    if not permissions.can_view_ticket(request.user, ticket):
        messages.error(request, "You do not have permission to view this ticket.")
        return redirect("tickets:dashboard")

    if request.method == "POST":
        action = request.POST.get("action", "message")
        if action == "manage" and permissions.can_manage_ticket(request.user):
            _handle_manage(request, ticket)
            return redirect("tickets:ticket_detail", pk=pk)
        # Default: post a message to the conversation.
        _handle_message(request, ticket)
        return redirect("tickets:ticket_detail", pk=pk)

    thread = permissions.visible_messages(request.user, ticket).prefetch_related("attachments")
    agents = User.objects.filter(role__in=["admin", "agent"])
    from .models import TicketRating

    rating = TicketRating.objects.filter(ticket=ticket).first()
    ctx = {
        "ticket": ticket,
        "messages_thread": thread,
        "can_edit": permissions.can_edit_ticket(request.user, ticket),
        "can_manage": permissions.can_manage_ticket(request.user),
        "can_assign": permissions.can_assign_ticket(request.user),
        "can_post_internal": permissions.can_post_internal(request.user),
        "agents": agents,
        "rating": rating,
        "can_rate": request.user.id == ticket.created_by_id
        and ticket.status in ("resolved", "closed"),
    }
    return render(request, "tickets/detail.html", ctx)


def _handle_message(request, ticket):
    """Create a reply or internal note from the composer form."""
    body = request.POST.get("body", "").strip()
    files = request.FILES.getlist("attachments")
    kind = request.POST.get("message_kind", "reply")
    # Only agents/admins may post internal notes.
    if kind == "note" and not permissions.can_post_internal(request.user):
        kind = "reply"
    if not body and not files:
        return
    try:
        msg = post_message(ticket, request.user, body, kind=kind, files=files)
    except AttachmentTooLarge as exc:
        messages.error(request, f"Attachment '{exc.name}' exceeds the size limit.")
        return
    ticket.save(update_fields=["updated_at"])
    if kind == "note":
        messages.success(request, "Internal note added.")
    else:
        messages.success(request, "Reply posted.")
    if kind == "reply":
        from apps.inbox.email_service import send_ticket_reply

        send_ticket_reply(msg)


def _handle_manage(request, ticket):
    """Apply assignee / priority / status changes and log system events."""
    actor = request.user
    assigned_user_ids = request.POST.get("assigned_users", "").strip()
    if assigned_user_ids:
        try:
            ids = [int(uid.strip()) for uid in assigned_user_ids.split(",") if uid.strip()]
            before = set(ticket.assigned_users.values_list("pk", flat=True))
            ticket.assigned_users.set(ids)
            if set(ids) != before:
                names = (
                    ", ".join(u.get_full_name() or u.username for u in ticket.assigned_users.all())
                    or "no one"
                )
                record_system_event(ticket, actor, f"Assignees set to {names}.")
        except (ValueError, TypeError):
            pass

    due_raw = request.POST.get("due_at", "").strip()
    new_due = parse_datetime(due_raw) if due_raw else None
    if new_due is not None and timezone.is_naive(new_due):
        new_due = timezone.make_aware(new_due)
    ticket.due_at = new_due

    new_priority = request.POST.get("priority", ticket.priority)
    if new_priority != ticket.priority:
        record_system_event(
            ticket,
            actor,
            f"Priority changed from {ticket.get_priority_display()} to "
            f"{dict(Ticket.PRIORITY_CHOICES).get(new_priority, new_priority)}.",
        )
        ticket.priority = new_priority

    new_status = request.POST.get("status", ticket.status)
    status_changed = ticket.status != new_status
    if status_changed:
        record_system_event(
            ticket,
            actor,
            f"Status changed from {ticket.get_status_display()} to "
            f"{dict(Ticket.STATUS_CHOICES).get(new_status, new_status)}.",
        )
        ticket.status = new_status
        if new_status in ("resolved", "closed"):
            ticket.closed_at = timezone.now()
        elif ticket.closed_at:
            ticket.closed_at = None

    ticket.save()
    if status_changed:
        from .events import ticket_status_changed

        ticket_status_changed.send(sender=Ticket, ticket=ticket, actor=actor, new_status=new_status)
    messages.success(request, f"Ticket #{ticket.pk} updated.")


@login_required
def attachment_download(request, pk):
    attachment = get_object_or_404(Attachment.objects.select_related("ticket", "message"), pk=pk)
    ticket = attachment.ticket
    if not permissions.can_view_ticket(request.user, ticket):
        raise Http404
    # Customers may only download attachments on public messages (or ticket-level).
    if request.user.role == "customer" and attachment.message and not attachment.message.is_public:
        raise Http404
    try:
        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=attachment.original_name,
        )
    except FileNotFoundError as exc:
        raise Http404 from exc


@login_required
def ticket_create(request):
    from apps.customfields.service import active_forms, get_form, save_field_values

    departments = Department.objects.all()
    forms = list(active_forms())
    form_slug = request.POST.get("form_slug") or request.GET.get("form", "")
    selected_form = get_form(form_slug) if form_slug else None

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        department_id = request.POST.get("department")
        tags = request.POST.get("tags", "").strip()

        if title and description:
            ticket = Ticket.objects.create(
                title=title,
                description=description,
                priority="medium"
                if request.user.role == "customer"
                else request.POST.get("priority", "medium"),
                created_by=request.user,
                department_id=department_id if department_id else None,
                tags="" if request.user.role == "customer" else tags,
            )
            if selected_form:
                save_field_values(ticket, selected_form, request.POST)
            messages.success(request, f"Ticket #{ticket.pk} created successfully.")
            return redirect("tickets:ticket_detail", pk=ticket.pk)
        else:
            messages.error(request, "Title and description are required.")

    ctx = {
        "departments": departments,
        "request_forms": forms,
        "selected_form": selected_form,
        "form_fields": selected_form.ordered_fields() if selected_form else [],
    }
    return render(request, "tickets/create.html", ctx)


@login_required
def ticket_edit(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)

    if not permissions.can_edit_ticket(request.user, ticket):
        messages.error(request, "You do not have permission to edit this ticket.")
        return redirect("tickets:ticket_detail", pk=pk)

    departments = Department.objects.all()

    if request.method == "POST":
        ticket.title = request.POST.get("title", ticket.title)
        ticket.description = request.POST.get("description", ticket.description)

        if request.user.role in ("agent", "admin"):
            ticket.priority = request.POST.get("priority", ticket.priority)
            ticket.status = request.POST.get("status", ticket.status)
            ticket.tags = request.POST.get("tags", "").strip()
            department_id = request.POST.get("department")
            ticket.department_id = department_id if department_id else None

            if ticket.status in ("resolved", "closed"):
                ticket.closed_at = timezone.now()
            else:
                ticket.closed_at = None
        else:
            pass

        ticket.save()
        messages.success(request, f"Ticket #{ticket.pk} updated successfully.")
        return redirect("tickets:ticket_detail", pk=pk)

    ctx = {"ticket": ticket, "departments": departments}
    return render(request, "tickets/edit.html", ctx)


@login_required
def ticket_assign(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)

    if not permissions.can_assign_ticket(request.user):
        messages.error(request, "You do not have permission to assign this ticket.")
        return redirect("tickets:ticket_detail", pk=pk)

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        agents = User.objects.filter(role__in=["admin", "agent"])
        if user_id:
            target = get_object_or_404(agents, pk=user_id)
            ticket.assigned_to = target
            ticket.save()
            record_system_event(
                ticket,
                request.user,
                f"Assigned to {target.get_full_name() or target.username}.",
            )
            from apps.notifications.service import notify

            notify(
                target, f"You were assigned to “{ticket.title}”", actor=request.user, ticket=ticket
            )
            messages.success(
                request,
                f"Ticket #{ticket.pk} assigned to {target.get_full_name() or target.username}.",
            )
        else:
            ticket.assigned_to = None
            ticket.save()
            messages.success(request, f"Ticket #{ticket.pk} unassigned.")
        return redirect("tickets:ticket_detail", pk=pk)

    agents = User.objects.filter(role__in=["admin", "agent"])
    ctx = {"ticket": ticket, "agents": agents}
    return render(request, "tickets/assign.html", ctx)


@login_required
def user_search(request):
    query = request.GET.get("q", "").strip()
    agents = User.objects.filter(role__in=["admin", "agent"])

    if query:
        agents = agents.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )

    agents = agents.values(
        "pk", "username", "first_name", "last_name", "email", "role", "avatar_color", "department"
    )
    result = list(agents)
    return JsonResponse({"users": result})


@login_required
def ticket_rate(request, pk):
    """Customer rates a resolved/closed ticket (CSAT)."""
    from .models import TicketRating

    ticket = get_object_or_404(Ticket, pk=pk)
    if ticket.created_by_id != request.user.id or ticket.status not in ("resolved", "closed"):
        return redirect("tickets:ticket_detail", pk=pk)
    if request.method == "POST":
        try:
            score = int(request.POST.get("score", "0"))
        except ValueError:
            score = 0
        if 1 <= score <= 5:
            TicketRating.objects.update_or_create(
                ticket=ticket,
                defaults={
                    "score": score,
                    "comment": request.POST.get("comment", "").strip(),
                    "created_by": request.user,
                },
            )
            messages.success(request, "Thanks for your feedback!")
    return redirect("tickets:ticket_detail", pk=pk)


@login_required
def ticket_export(request):
    """Export tickets as CSV (staff only) — enterprise data export."""
    import csv

    from django.http import HttpResponse

    if request.user.role not in ("agent", "admin"):
        return redirect("tickets:dashboard")

    def safe(value):
        """Neutralize CSV formula injection: prefix cells that a spreadsheet
        would treat as a formula with a leading apostrophe."""
        text = "" if value is None else str(value)
        if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + text
        return text

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="jackil-tickets.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "ID",
            "Title",
            "Status",
            "Priority",
            "Source",
            "Created by",
            "Requester email",
            "Assigned to",
            "Department",
            "Tags",
            "Created",
            "Resolution due",
            "Closed",
        ]
    )
    for t in Ticket.objects.select_related("created_by", "assigned_to", "department"):
        writer.writerow(
            [
                safe(t.id),
                safe(t.title),
                safe(t.get_status_display()),
                safe(t.get_priority_display()),
                safe(t.source),
                safe(
                    t.created_by.get_full_name() or t.created_by.username if t.created_by_id else ""
                ),
                safe(t.requester_email),
                safe(
                    (t.assigned_to.get_full_name() or t.assigned_to.username)
                    if t.assigned_to_id
                    else ""
                ),
                safe(t.department.name if t.department_id else ""),
                safe(t.tags),
                t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "",
                t.resolution_due.strftime("%Y-%m-%d %H:%M") if t.resolution_due else "",
                t.closed_at.strftime("%Y-%m-%d %H:%M") if t.closed_at else "",
            ]
        )
    return response


@login_required
def activity_log(request):
    """Recent audit trail across tickets (staff only)."""
    if request.user.role not in ("agent", "admin"):
        return redirect("tickets:dashboard")
    from .models import TicketMessage

    events = (
        TicketMessage.objects.filter(kind="system")
        .select_related("author", "ticket")
        .order_by("-created_at")[:100]
    )
    return render(request, "tickets/activity.html", {"events": events})


@login_required
def global_search(request):
    query = request.GET.get("q", "").strip()
    tickets = []
    articles = []
    if query:
        tq = Ticket.objects.select_related("created_by", "assigned_to")
        # Customers only match on public message bodies (never internal notes),
        # so a search term can't reveal the existence/content of a private note.
        if request.user.role == "customer":
            tq = tq.filter(created_by=request.user)
            message_match = Q(messages__body__icontains=query, messages__is_public=True)
        else:
            message_match = Q(messages__body__icontains=query)
        tickets = tq.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(tags__icontains=query)
            | message_match
        ).distinct()[:25]

        from apps.kb.service import public_only_for, search_articles

        articles = search_articles(query, public_only=public_only_for(request.user))[:10]

    ctx = {
        "query": query,
        "tickets": tickets,
        "articles": articles,
        "result_count": len(tickets) + len(articles),
    }
    return render(request, "tickets/search.html", ctx)


@login_required
def macro_list(request):
    """Canned responses available to the current agent (for the composer)."""
    if request.user.role not in ("agent", "admin"):
        return JsonResponse({"macros": []})
    from apps.automation.models import Macro

    macros = Macro.objects.filter(Q(is_shared=True) | Q(created_by=request.user)).values(
        "id", "name", "body"
    )
    return JsonResponse({"macros": list(macros)})

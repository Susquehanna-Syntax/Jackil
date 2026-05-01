from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
from .models import Ticket, TicketComment
from apps.accounts.models import Department
from apps.accounts.models import User


def dashboard(request):
    if request.user.is_authenticated:
        return dashboard_auth(request)
    return render(request, "tickets/dashboard_public.html")


@login_required
def dashboard_auth(request):
    total = Ticket.objects.count()
    open_tickets = Ticket.objects.filter(status="open")
    my_open = open_tickets.filter(assigned_to=request.user).count()
    open_total = open_tickets.count()
    in_progress = Ticket.objects.filter(status="in_progress").count()
    resolved = Ticket.objects.filter(status="resolved").count()
    closed = Ticket.objects.filter(status="closed").count()

    critical = Ticket.objects.filter(priority="critical", status__in=["open", "in_progress"]).count()

    recent = Ticket.objects.select_related("created_by", "assigned_to", "department")[:8]
    my_tickets = Ticket.objects.filter(assigned_to=request.user).select_related("created_by", "assigned_to", "department")[:5]

    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    this_week = Ticket.objects.filter(created_at__date__gte=week_ago).count()

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
    }
    return render(request, "tickets/dashboard.html", ctx)


@login_required
def ticket_list(request):
    tickets = Ticket.objects.select_related("created_by", "assigned_to", "department")

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
            Q(title__icontains=search) | Q(description__icontains=search) | Q(tags__icontains=search)
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
    comments = ticket.comments.select_related("author").order_by("created_at")

    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if body:
            TicketComment.objects.create(ticket=ticket, author=request.user, body=body)
            return redirect("tickets:ticket_detail", pk=pk)

    ctx = {"ticket": ticket, "comments": comments}
    return render(request, "tickets/detail.html", ctx)


@login_required
def ticket_create(request):
    departments = Department.objects.all()

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        priority = request.POST.get("priority", "medium")
        department_id = request.POST.get("department")
        tags = request.POST.get("tags", "").strip()

        if title and description:
            ticket = Ticket.objects.create(
                title=title,
                description=description,
                priority=priority,
                created_by=request.user,
                department_id=department_id if department_id else None,
                tags=tags,
            )
            messages.success(request, f"Ticket #{ticket.pk} created successfully.")
            return redirect("tickets:ticket_detail", pk=ticket.pk)
        else:
            messages.error(request, "Title and description are required.")

    ctx = {"departments": departments}
    return render(request, "tickets/create.html", ctx)


@login_required
def ticket_edit(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)

    if ticket.assigned_to != request.user and request.user.role != "admin":
        messages.error(request, "You don't have permission to edit this ticket.")
        return redirect("tickets:ticket_detail", pk=pk)

    departments = Department.objects.all()

    if request.method == "POST":
        ticket.title = request.POST.get("title", ticket.title)
        ticket.description = request.POST.get("description", ticket.description)
        ticket.priority = request.POST.get("priority", ticket.priority)
        ticket.status = request.POST.get("status", ticket.status)

        department_id = request.POST.get("department")
        ticket.department_id = department_id if department_id else None

        tags = request.POST.get("tags", "").strip()
        ticket.tags = tags

        if ticket.status in ("resolved", "closed"):
            ticket.closed_at = timezone.now()
        else:
            ticket.closed_at = None

        ticket.save()
        messages.success(request, f"Ticket #{ticket.pk} updated successfully.")
        return redirect("tickets:ticket_detail", pk=pk)

    ctx = {"ticket": ticket, "departments": departments}
    return render(request, "tickets/edit.html", ctx)


@login_required
def ticket_assign(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)

    if request.user.role != "admin":
        if ticket.assigned_to != request.user:
            messages.error(request, "You don't have permission to assign this ticket.")
            return redirect("tickets:ticket_detail", pk=pk)

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        if user_id:
            ticket.assigned_to = get_object_or_404(User, pk=user_id)
            ticket.save()
            messages.success(request, f"Ticket #{ticket.pk} assigned successfully.")
        else:
            ticket.assigned_to = None
            ticket.save()
            messages.success(request, f"Ticket #{ticket.pk} unassigned.")
        return redirect("tickets:ticket_detail", pk=pk)

    agents = User.objects.filter(role__in=["admin", "agent"])
    ctx = {"ticket": ticket, "agents": agents}
    return render(request, "tickets/assign.html", ctx)
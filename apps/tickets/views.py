from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils import timezone
from django.http import JsonResponse
from datetime import timedelta
from .models import Ticket, TicketComment
from apps.accounts.models import Department, User


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
    critical = Ticket.objects.filter(priority="critical", status__in=["open", "in_progress"]).count()
    recent = Ticket.objects.select_related("created_by", "assigned_to", "department").prefetch_related("assigned_users")[:8]
    my_tickets = Ticket.objects.filter(assigned_to=request.user).select_related("created_by", "assigned_to", "department").prefetch_related("assigned_users")[:5]
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
def customer_tickets(request):
    tickets = Ticket.objects.filter(created_by=request.user).select_related(
        "assigned_to", "department"
    ).prefetch_related("assigned_users").order_by("-created_at")

    status = request.GET.get("status")
    search = request.GET.get("search", "").strip()

    if status:
        tickets = tickets.filter(status=status)
    if search:
        tickets = tickets.filter(
            Q(title__icontains=search) | Q(description__icontains=search)
        )

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

    tickets = Ticket.objects.select_related("created_by", "assigned_to", "department").prefetch_related("assigned_users")

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

    if request.user.role == "customer" and ticket.created_by != request.user:
        messages.error(request, "You do not have permission to view this ticket.")
        return redirect("tickets:customer_tickets")

    comments = ticket.comments.select_related("author").order_by("created_at")

    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if body:
            TicketComment.objects.create(ticket=ticket, author=request.user, body=body)
            return redirect("tickets:ticket_detail", pk=pk)

        if request.user.role in ("agent", "admin"):
            assigned_user_ids = request.POST.get("assigned_users", "").strip()
            if assigned_user_ids:
                try:
                    ids = [int(uid.strip()) for uid in assigned_user_ids.split(",") if uid.strip()]
                    ticket.assigned_users.set(ids)
                except (ValueError, TypeError):
                    pass
            ticket.priority = request.POST.get("priority", ticket.priority)
            new_status = request.POST.get("status", ticket.status)

            if ticket.status != new_status:
                ticket.status = new_status
                if new_status in ("resolved", "closed"):
                    ticket.closed_at = timezone.now()
                elif ticket.closed_at:
                    ticket.closed_at = None

            ticket.save()
            messages.success(request, f"Ticket #{ticket.pk} updated.")
            return redirect("tickets:ticket_detail", pk=pk)

    agents = User.objects.filter(role__in=["admin", "agent"])
    ctx = {
        "ticket": ticket,
        "comments": comments,
        "can_edit": _can_edit(request.user, ticket),
        "can_manage": _can_manage(request.user, ticket),
        "can_assign": _can_assign(request.user, ticket),
        "agents": agents,
    }
    return render(request, "tickets/detail.html", ctx)


@login_required
def ticket_create(request):
    departments = Department.objects.all()

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        department_id = request.POST.get("department")
        tags = request.POST.get("tags", "").strip()

        if title and description:
            ticket = Ticket.objects.create(
                title=title,
                description=description,
                priority="medium" if request.user.role == "customer" else request.POST.get("priority", "medium"),
                created_by=request.user,
                department_id=department_id if department_id else None,
                tags="" if request.user.role == "customer" else tags,
            )
            messages.success(request, f"Ticket #{ticket.pk} created successfully.")
            return redirect("tickets:ticket_detail", pk=ticket.pk)
        else:
            messages.error(request, "Title and description are required.")

    ctx = {
        "departments": departments,
    }
    return render(request, "tickets/create.html", ctx)


@login_required
def ticket_edit(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)

    if not _can_edit(request.user, ticket):
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

    if not _can_assign(request.user, ticket):
        messages.error(request, "You do not have permission to assign this ticket.")
        return redirect("tickets:ticket_detail", pk=pk)

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        agents = User.objects.filter(role__in=["admin", "agent"])
        if user_id:
            target = get_object_or_404(agents, pk=user_id)
            ticket.assigned_to = target
            ticket.save()
            messages.success(request, f"Ticket #{ticket.pk} assigned to {target.get_full_name() or target.username}.")
        else:
            ticket.assigned_to = None
            ticket.save()
            messages.success(request, f"Ticket #{ticket.pk} unassigned.")
        return redirect("tickets:ticket_detail", pk=pk)

    agents = User.objects.filter(role__in=["admin", "agent"])
    ctx = {"ticket": ticket, "agents": agents}
    return render(request, "tickets/assign.html", ctx)


def _can_edit(user, ticket):
    if user.role == "admin":
        return True
    if user.role == "agent":
        return True
    if user.role == "customer":
        return ticket.created_by == user
    return False


def _can_manage(user, ticket):
    return user.role in ("admin", "agent")


def _can_assign(user, ticket):
    if user.role == "admin":
        return True
    if user.role == "agent":
        return True
    return False


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

    agents = agents.values("pk", "username", "first_name", "last_name", "email", "role", "avatar_color", "department")
    result = list(agents)
    return JsonResponse({"users": result})
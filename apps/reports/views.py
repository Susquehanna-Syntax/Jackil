from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.accounts.models import User
from apps.sla.service import resolution_status, response_status
from apps.tickets.models import Ticket

STATUS_COLORS = {
    "open": "sky",
    "in_progress": "peach",
    "pending": "lemon",
    "resolved": "mint",
    "closed": "text-3",
}
PRIORITY_COLORS = {"critical": "coral", "high": "rose", "medium": "lavender", "low": "mint"}


def _avg_hours(deltas):
    if not deltas:
        return None
    total = sum(d.total_seconds() for d in deltas)
    return round(total / len(deltas) / 3600, 1)


@login_required
def reports_home(request):
    if request.user.role not in ("agent", "admin"):
        return redirect("tickets:dashboard")

    tickets = Ticket.objects.all()
    total = tickets.count()
    now = timezone.now()

    # Status + priority breakdowns
    status_counts = dict(tickets.values_list("status").annotate(n=Count("id")))
    priority_counts = dict(tickets.values_list("priority").annotate(n=Count("id")))
    status_rows = [
        {
            "label": dict(Ticket.STATUS_CHOICES)[s],
            "count": status_counts.get(s, 0),
            "color": STATUS_COLORS.get(s, "lavender"),
            "pct": round(status_counts.get(s, 0) / total * 100) if total else 0,
        }
        for s, _ in Ticket.STATUS_CHOICES
    ]
    priority_rows = [
        {
            "label": dict(Ticket.PRIORITY_CHOICES)[p],
            "count": priority_counts.get(p, 0),
            "color": PRIORITY_COLORS.get(p, "lavender"),
            "pct": round(priority_counts.get(p, 0) / total * 100) if total else 0,
        }
        for p, _ in Ticket.PRIORITY_CHOICES
    ]

    # 14-day created volume
    start = (now - timedelta(days=13)).date()
    per_day = dict(
        tickets.filter(created_at__date__gte=start)
        .annotate(d=TruncDate("created_at"))
        .values_list("d")
        .annotate(n=Count("id"))
    )
    volume = []
    peak = max(per_day.values()) if per_day else 1
    for i in range(14):
        day = start + timedelta(days=i)
        n = per_day.get(day, 0)
        volume.append({"day": day, "n": n, "pct": round(n / peak * 100) if peak else 0})

    # SLA compliance
    resp_met = resp_breached = res_met = res_breached = 0
    first_response_deltas = []
    resolution_deltas = []
    for t in tickets.only(
        "first_response_due",
        "first_responded_at",
        "resolution_due",
        "status",
        "closed_at",
        "created_at",
    ):
        rs = response_status(t, now)
        if rs == "met":
            resp_met += 1
        elif rs == "breached":
            resp_breached += 1
        res = resolution_status(t, now)
        if res == "met":
            res_met += 1
        elif res == "breached":
            res_breached += 1
        if t.first_responded_at and t.created_at:
            first_response_deltas.append(t.first_responded_at - t.created_at)
        if t.status in ("resolved", "closed") and t.closed_at and t.created_at:
            resolution_deltas.append(t.closed_at - t.created_at)

    resp_total = resp_met + resp_breached
    res_total = res_met + res_breached

    # Top agents by assigned ticket load
    top_agents = list(
        User.objects.filter(role__in=["agent", "admin"])
        .annotate(load=Count("assigned_tickets"))
        .values("first_name", "last_name", "username", "avatar_color", "load")
        .order_by("-load")[:6]
    )

    ctx = {
        "total": total,
        "resolved_total": status_counts.get("resolved", 0) + status_counts.get("closed", 0),
        "open_total": status_counts.get("open", 0),
        "status_rows": status_rows,
        "priority_rows": priority_rows,
        "volume": volume,
        "volume_total": sum(v["n"] for v in volume),
        "resp_met": resp_met,
        "resp_total": resp_total,
        "resp_pct": round(resp_met / resp_total * 100) if resp_total else 0,
        "res_met": res_met,
        "res_total": res_total,
        "res_pct": round(res_met / res_total * 100) if res_total else 0,
        "avg_first_response_h": _avg_hours(first_response_deltas),
        "avg_resolution_h": _avg_hours(resolution_deltas),
        "top_agents": top_agents,
    }
    return render(request, "reports/home.html", ctx)

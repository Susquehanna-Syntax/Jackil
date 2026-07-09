from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.inbox.models import Inbox
from apps.sla.models import WEEKDAYS, BusinessSchedule, SLATarget

from .decorators import admin_required
from .forms import InboxForm


@admin_required
def settings_home(request):
    ctx = {
        "inbox_count": Inbox.objects.count(),
        "active_inbox_count": Inbox.objects.filter(active=True).count(),
        "default_inbox": Inbox.get_default(),
        "section": "home",
    }
    return render(request, "console/settings_home.html", ctx)


@admin_required
def inbox_list(request):
    ctx = {"inboxes": Inbox.objects.all(), "section": "email"}
    return render(request, "console/inbox_list.html", ctx)


@admin_required
def inbox_create(request):
    return _inbox_form(request, None)


@admin_required
def inbox_edit(request, pk):
    return _inbox_form(request, get_object_or_404(Inbox, pk=pk))


def _inbox_form(request, inbox):
    if request.method == "POST":
        form = InboxForm(request.POST, instance=inbox)
        if form.is_valid():
            obj = form.save()
            _enforce_single_default(obj)
            messages.success(request, f"Inbox “{obj.name}” saved.")
            return redirect("console:inbox_list")
    else:
        form = InboxForm(instance=inbox)
    ctx = {"form": form, "inbox": inbox, "section": "email"}
    return render(request, "console/inbox_form.html", ctx)


@admin_required
def inbox_delete(request, pk):
    inbox = get_object_or_404(Inbox, pk=pk)
    if request.method == "POST":
        name = inbox.name
        inbox.delete()
        messages.success(request, f"Inbox “{name}” deleted.")
        return redirect("console:inbox_list")
    return render(
        request, "console/inbox_confirm_delete.html", {"inbox": inbox, "section": "email"}
    )


def _enforce_single_default(inbox):
    """Only one inbox may be the default."""
    if inbox.is_default:
        Inbox.objects.exclude(pk=inbox.pk).filter(is_default=True).update(is_default=False)


@admin_required
def sla_settings(request):
    targets = list(SLATarget.objects.all())
    schedule = BusinessSchedule.active()
    if schedule is None:
        schedule = BusinessSchedule.objects.create(name="Default schedule")

    if request.method == "POST":
        for target in targets:
            resp = request.POST.get(f"response_{target.priority}")
            reso = request.POST.get(f"resolution_{target.priority}")
            if resp and resp.isdigit():
                target.response_minutes = int(resp)
            if reso and reso.isdigit():
                target.resolution_minutes = int(reso)
            target.active = request.POST.get(f"active_{target.priority}") == "on"
            target.save()

        schedule.mode = request.POST.get("mode", schedule.mode)
        schedule.workday_start = request.POST.get("workday_start") or schedule.workday_start
        schedule.workday_end = request.POST.get("workday_end") or schedule.workday_end
        selected_days = request.POST.getlist("workdays")
        if selected_days:
            schedule.workdays = ",".join(d for d in selected_days if d.isdigit())
        schedule.save()

        messages.success(request, "SLA policies updated.")
        return redirect("console:sla_settings")

    ctx = {
        "targets": targets,
        "schedule": schedule,
        "weekdays": WEEKDAYS,
        "schedule_days": schedule.workday_set(),
        "section": "sla",
    }
    return render(request, "console/sla_settings.html", ctx)

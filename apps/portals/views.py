"""The admin portal pages."""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.console.decorators import admin_required

from . import service
from .forms import PortalForm
from .models import Portal

BUSINESS_HINT = "More than one portal is part of SQSY Business."


@admin_required
def portal_list(request):
    return render(
        request,
        "portals/settings.html",
        {
            "portals": Portal.objects.all(),
            "can_add": service.can_add_portal(),
            "section": "portals",
        },
    )


@admin_required
def portal_create(request):
    styling = service.styling_enabled()
    if not service.can_add_portal():
        messages.error(request, BUSINESS_HINT)
        return redirect("console:portal_list")

    form = PortalForm(request.POST or None, styling=styling)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # Locking the seeded portals stops two admins both claiming the
            # one free portal; with the feature on no lock is needed.
            if not service.styling_enabled():
                Portal.objects.filter(is_default=True).select_for_update().first()
            if not service.can_add_portal():
                messages.error(request, BUSINESS_HINT)
                return redirect("console:portal_list")
            portal = form.save()
        messages.success(request, f"Portal “{portal.name}” created.")
        return redirect("console:portal_edit", pk=portal.pk)

    return render(
        request,
        "portals/edit.html",
        {"form": form, "portal": None, "styling": styling, "section": "portals"},
    )


@admin_required
def portal_edit(request, pk):
    portal = get_object_or_404(Portal, pk=pk)
    styling = service.styling_enabled()

    form = PortalForm(request.POST or None, instance=portal, styling=styling)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Portal “{portal.name}” saved.")
        return redirect("console:portal_edit", pk=portal.pk)

    return render(
        request,
        "portals/edit.html",
        {
            "form": form,
            "portal": portal,
            "styling": styling,
            "section": "portals",
        },
    )


@admin_required
@require_POST
def portal_delete(request, pk):
    portal = get_object_or_404(Portal, pk=pk)
    if portal.is_default:
        messages.error(request, "Make another portal the default first.")
        return redirect("console:portal_list")

    portal.delete()
    messages.success(request, "Portal deleted.")
    return redirect("console:portal_list")

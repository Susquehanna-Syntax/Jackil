"""The admin portal pages."""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.console.decorators import admin_required

from . import service
from .forms import PortalForm
from .models import Portal

BUSINESS_HINT = "More than one portal is part of SQSY Business."


@admin_required
def portal_list(request):
    portals = list(Portal.objects.prefetch_related("spaces"))
    for portal in portals:
        # The address people are sent to, whole, so it can be copied as is.
        portal.public_url = request.build_absolute_uri(
            reverse("portals:portal", kwargs={"slug": portal.slug})
        )
    return render(
        request,
        "portals/settings.html",
        {
            "portals": portals,
            "can_add": service.can_add_portal(),
            "section": "portals",
        },
    )


@admin_required
@require_POST
def portal_publish(request, pk):
    """Publish or unpublish from the list, without opening the editor."""
    portal = get_object_or_404(Portal, pk=pk)
    publish = request.POST.get("published") == "1"
    if not publish and portal.is_default:
        messages.error(request, "Make another portal the default before unpublishing this one.")
        return redirect("console:portal_list")
    portal.is_published = publish
    portal.save(update_fields=["is_published", "updated_at"])
    if publish:
        messages.success(request, f"“{portal.name}” is published.")
    else:
        messages.success(request, f"“{portal.name}” is a draft again: only staff can open it.")
    return redirect("console:portal_list")


@admin_required
@require_POST
def portal_make_default(request, pk):
    """The default portal is where /portal/ and the help links land, so it
    must be one people can open."""
    portal = get_object_or_404(Portal, pk=pk)
    if not portal.is_published:
        messages.error(request, "Publish this portal before making it the default.")
        return redirect("console:portal_list")
    portal.is_default = True
    portal.save()
    messages.success(request, f"“{portal.name}” is now the default portal.")
    return redirect("console:portal_list")


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

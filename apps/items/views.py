from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.vigil.client import VigilUnavailable, get_client
from apps.vigil.hosts import host_for, suggest_host
from apps.vigil.links import DOWN_KEY

from .forms import ItemForm, ItemKindForm
from .models import Item, ItemKind
from .permissions import (
    can_delete_items,
    can_edit_items,
    can_manage_kinds,
    can_view_items,
)


@login_required
def item_list(request):
    if not can_view_items(request.user):
        raise PermissionDenied
    items = Item.objects.select_related("kind", "owner", "department")

    query = request.GET.get("q", "").strip()
    kind_slug = request.GET.get("kind", "").strip()
    if query:
        items = items.filter(
            Q(name__icontains=query) | Q(vendor__icontains=query) | Q(notes__icontains=query)
        )
    if kind_slug:
        items = items.filter(kind__slug=kind_slug)

    ctx = {
        "items": items,
        "kinds": ItemKind.objects.all(),
        "query": query,
        "kind_slug": kind_slug,
        "can_manage_kinds": can_manage_kinds(request.user),
    }
    return render(request, "items/list.html", ctx)


@login_required
def item_detail(request, pk):
    if not can_view_items(request.user):
        raise PermissionDenied
    item = get_object_or_404(Item.objects.select_related("kind", "owner", "department"), pk=pk)
    ctx = {
        "item": item,
        "attributes": sorted((item.attributes or {}).items()),
        "can_edit": can_edit_items(request.user),
        "can_delete": can_delete_items(request.user),
    }
    ctx["vigil_host"] = host_for(item, request.user)
    ctx["vigil_suggestion"] = (
        suggest_host(item, request.user) if ctx["can_edit"] and ctx["vigil_host"] is None else None
    )
    ctx["vigil_down"] = bool(cache.get(DOWN_KEY))
    return render(request, "items/detail.html", ctx)


@login_required
def item_link_host(request, pk):
    if not can_edit_items(request.user):
        raise PermissionDenied
    item = get_object_or_404(Item, pk=pk)
    host_id = (request.POST.get("host_id") or "").strip()
    item.vigil_host_id = host_id[:64]
    item.save(update_fields=["vigil_host_id", "updated_at"])
    if host_id:
        client = get_client()
        label = host_id
        if client is not None:
            try:
                host = client.detail("host", host_id)
            except VigilUnavailable:
                host = None
            if host:
                label = str(host.get("label") or host_id)
        messages.success(request, f"Linked to Vigil host {label}.")
    else:
        messages.success(request, "Vigil host cleared.")
    return redirect(item)


@login_required
def item_create(request):
    if not can_edit_items(request.user):
        raise PermissionDenied
    form = ItemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = form.save()
        messages.success(request, f"Item “{item.name}” created.")
        return redirect(item.get_absolute_url())
    return render_form(request, "New Item", form, "Create Item")


@login_required
def item_edit(request, pk):
    if not can_edit_items(request.user):
        raise PermissionDenied
    item = get_object_or_404(Item, pk=pk)
    form = ItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Item “{item.name}” updated.")
        return redirect(item.get_absolute_url())
    return render_form(request, f"Edit {item.name}", form, "Save Changes")


@login_required
def item_delete(request, pk):
    if not can_delete_items(request.user):
        raise PermissionDenied
    item = get_object_or_404(Item, pk=pk)
    if request.method == "POST":
        name = item.name
        item.delete()
        messages.success(request, f"Item “{name}” deleted.")
        return redirect("items:item_list")
    return render(
        request,
        "items/confirm_delete.html",
        {"item": item, "cancel_url": item.get_absolute_url()},
    )


@login_required
def kind_list(request):
    if not can_manage_kinds(request.user):
        raise PermissionDenied
    if request.method == "POST":
        form = ItemKindForm(request.POST)
        if form.is_valid():
            kind = form.save()
            messages.success(request, f"Kind “{kind.name}” added.")
        else:
            messages.error(request, "That kind could not be added.")
        return redirect("items:kind_list")
    ctx = {
        "kinds": ItemKind.objects.all(),
        "form": ItemKindForm(),
    }
    return render(request, "items/kinds.html", ctx)


@login_required
def kind_delete(request, pk):
    if not can_manage_kinds(request.user):
        raise PermissionDenied
    kind = get_object_or_404(ItemKind, pk=pk)
    if request.method == "POST":
        if kind.items.exists():
            messages.error(request, f"“{kind.name}” still has Items. Move them first.")
        else:
            kind.delete()
            messages.success(request, f"Kind “{kind.name}” deleted.")
        return redirect("items:kind_list")
    return redirect("items:kind_list")


def render_form(request, title, form, submit_label):
    return render(
        request,
        "items/form.html",
        {"title": title, "form": form, "submit_label": submit_label},
    )

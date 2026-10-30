from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.links.models import DynamicLink
from apps.tickets.models import Ticket
from apps.ui.live import render_live
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

#: Statuses that mean a linked ticket is no longer open.
CLOSED_TICKET_STATUSES = ["resolved", "closed"]

#: How far ahead the "Warranty ending" chip looks.
WARRANTY_WINDOW_DAYS = 90

#: The quick chips under the kind tabs, in display order.
CHIP_LABELS = [
    ("warranty", "Warranty ending"),
    ("mine", "Mine"),
    ("unowned", "No owner"),
    ("open_tickets", "Has open tickets"),
]

#: Kind colours with no matching ``.t-*`` tab class of their own.
TAB_COLOURS = {"lavender": "lav", "coral": "rose"}


def _tab_colour(icon_color):
    return TAB_COLOURS.get(icon_color, icon_color)


def _open_ticket_item_ids():
    """Item pks with a link, in either direction, to a ticket still open.

    Two queries, one per direction; the join runs on the link table's own
    (type, id) index because a DynamicLink end is addressed by type and id
    rather than by a foreign key. The id sets are built separately so an Item
    pk can never be matched against a ticket number that happens to equal it.
    """
    item_pks = {str(pk) for pk in Item.objects.values_list("pk", flat=True)}
    as_source = DynamicLink.objects.filter(
        source_type="item",
        target_type="ticket",
        source_id__in=item_pks,
    ).values_list("source_id", "target_id")
    as_target = DynamicLink.objects.filter(
        source_type="ticket",
        target_type="item",
        target_id__in=item_pks,
    ).values_list("target_id", "source_id")

    open_tickets = set(
        Ticket.objects.exclude(status__in=CLOSED_TICKET_STATUSES).values_list("pk", flat=True)
    )
    ticket_ids = {str(pk) for pk in open_tickets}
    return {
        item_id
        for item_id, ticket_id in list(as_source) + list(as_target)
        if ticket_id in ticket_ids
    }


@login_required
def item_list(request):
    if not can_view_items(request.user):
        raise PermissionDenied

    query = request.GET.get("q", "").strip()
    kind_slug = request.GET.get("kind", "").strip()
    chips = [
        {"name": name, "label": label, "checked": bool(request.GET.get(name))}
        for name, label in CHIP_LABELS
    ]

    items = Item.objects.select_related("kind", "owner", "department")
    if query:
        items = items.filter(
            Q(name__icontains=query) | Q(vendor__icontains=query) | Q(notes__icontains=query)
        )
    if kind_slug:
        items = items.filter(kind__slug=kind_slug)
    checked = {chip["name"] for chip in chips if chip["checked"]}
    today = date.today()
    if "warranty" in checked:
        items = items.filter(
            warranty_end__gte=today, warranty_end__lte=today + timedelta(days=WARRANTY_WINDOW_DAYS)
        )
    if "mine" in checked:
        items = items.filter(owner=request.user)
    if "unowned" in checked:
        items = items.filter(owner__isnull=True)
    if "open_tickets" in checked:
        items = items.filter(pk__in=_open_ticket_item_ids())

    kinds = list(ItemKind.objects.all())
    counts = {kind.pk: kind.items.count() for kind in kinds}
    tabs = [
        {
            "label": "All",
            "colour": "all",
            "count": Item.objects.count(),
            "url": "?",
            "active": not kind_slug,
            "value": "",
        }
    ]
    tabs += [
        {
            "label": kind.name,
            "colour": _tab_colour(kind.icon_color),
            "count": counts[kind.pk],
            "url": f"?kind={kind.slug}",
            "active": kind.slug == kind_slug,
            "value": kind.slug,
        }
        for kind in kinds
    ]

    ctx = {
        "items": items,
        "kinds": kinds,
        "query": query,
        "kind_slug": kind_slug,
        "tabs": tabs,
        "chips": chips,
        "can_manage_kinds": can_manage_kinds(request.user),
    }
    return render_live(request, "items/list.html", "items/_results.html", ctx)


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
        messages.success(request, f"Dynamic Item “{item.name}” created.")
        return redirect(item.get_absolute_url())
    return render_form(request, "New Dynamic Item", form, "Create Dynamic Item")


@login_required
def item_edit(request, pk):
    if not can_edit_items(request.user):
        raise PermissionDenied
    item = get_object_or_404(Item, pk=pk)
    form = ItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Dynamic Item “{item.name}” updated.")
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
        messages.success(request, f"Dynamic Item “{name}” deleted.")
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
    form = ItemKindForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        kind = form.save()
        messages.success(request, f"Kind “{kind.name}” added.")
        return redirect("items:kind_list")
    ctx = {
        "kinds": ItemKind.objects.annotate(item_count=Count("items")),
        "form": form,
    }
    return render(request, "items/kinds.html", ctx)


@login_required
def kind_delete(request, pk):
    if not can_manage_kinds(request.user):
        raise PermissionDenied
    kind = get_object_or_404(ItemKind, pk=pk)
    if request.method == "POST":
        if kind.items.exists():
            messages.error(request, f"“{kind.name}” still has Dynamic Items. Move them first.")
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

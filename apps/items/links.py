import re
from dataclasses import replace

from django.urls import reverse

from apps.links.registry import LinkTarget, Resolver, register_type

from .models import Item
from .permissions import can_view_items

#: A path ending /items/<digits>/, with or without a scheme and host.
_ITEM_URL = re.compile(r"(?:^|/)items/(\d+)/$")


class ItemResolver(Resolver):
    def resolve(self, ids: list[str], user) -> dict[str, LinkTarget]:
        if not can_view_items(user):
            return {}
        numeric = [int(i) for i in ids if i.isdigit()]
        return {
            str(item.pk): _target(item)
            for item in Item.objects.filter(pk__in=numeric).select_related("kind")
        }

    def search(self, q: str, user, limit: int) -> list[LinkTarget]:
        if not can_view_items(user):
            return []
        term = q.strip()
        if not term:
            return []
        items = (
            Item.objects.filter(name__icontains=term) | Item.objects.filter(vendor__icontains=term)
        ).select_related("kind")[:limit]
        return [_target(item) for item in items]

    def recent(self, user, limit: int) -> list[LinkTarget]:
        if not can_view_items(user):
            return []
        items = Item.objects.select_related("kind", "owner").order_by("name")[:limit]
        return [_target(item) for item in items]

    def preview(self, id: str, user) -> LinkTarget | None:
        if not can_view_items(user):
            return None
        item = (
            Item.objects.select_related("kind", "owner").filter(pk=id).first()
            if id.isdigit()
            else None
        )
        if item is None:
            return None
        owner = item.owner
        owner_name = (owner.get_full_name() or owner.username) if owner else ""
        warranty = item.warranty_end.strftime("%d %b %Y") if item.warranty_end else "Not set"
        return replace(
            _target(item),
            facts=(
                ("Kind", item.kind.name),
                ("Vendor", item.vendor or "None"),
                ("Warranty ends", warranty),
                ("Owner", owner_name or "No owner"),
            ),
        )

    def from_url(self, url: str) -> str | None:
        match = _ITEM_URL.search(url)
        return match.group(1) if match else None


def _target(item) -> LinkTarget:
    return LinkTarget(
        type="item",
        id=str(item.pk),
        label=item.name,
        url=reverse("items:item_detail", args=[item.pk]),
        status=item.kind.name,
        tone="info",
    )


def register_item_type() -> None:
    register_type("item", ItemResolver())

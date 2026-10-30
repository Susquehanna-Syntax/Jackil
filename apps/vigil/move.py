"""Moving Jackil's device-like Dynamic Items into Vigil, links and all."""

from django.db import transaction

from apps.links.models import DynamicLink
from apps.links.registry import get_resolver
from apps.vigil.client import VigilUnavailable, get_client
from apps.vigil.devices import device_payload

#: The link end a moved item's links leave, and the two they can arrive at.
ITEM_END = "item"
DEVICE_END = "vigil:device"
HOST_END = "vigil:host"

#: Shown on the settings page while Vigil has this key marked read-only.
KEY_CANNOT_WRITE = (
    "Vigil does not let this key change devices yet. In Vigil, tick Can change "
    "devices on Jackil's key (Settings > Integrations)."
)


class SuggestionUnavailable(Exception):
    """Vigil could not say what the item matches; str(exc) is a sentence."""


def movable_items():
    """The device-like items Vigil is about to hold instead of Jackil."""
    from apps.items.models import Item

    return Item.objects.filter(kind__is_device_like=True).order_by("name")


def suggest_match(client, item) -> dict | None:
    """The Vigil device or host whose name already *is* this item's name.

    A name that merely resembles it is not a match: putting work on the wrong
    machine costs more than one device created twice and merged by hand.
    """
    name = item.name.strip().casefold()
    for end, type in ((DEVICE_END, "device"), (HOST_END, "host")):
        try:
            results = client.search(item.name, type)
        except VigilUnavailable as exc:
            raise SuggestionUnavailable(str(exc)) from None
        for row in results:
            if str(row.get("label") or "").strip().casefold() == name:
                return {
                    "type": end,
                    "id": str(row.get("id") or ""),
                    "label": str(row.get("label") or item.name),
                }
    return None


def move_item(client, item, match: dict | None, user) -> str:
    """Move one Item into Vigil and name the link end it moved to.

    An item that already has a ``vigil_device_id`` was created in Vigil by an
    earlier run that stopped before the delete; its device is reused, never
    created a second time.
    """
    if item.vigil_device_id:
        target = f"{DEVICE_END}:{item.vigil_device_id}"
    elif match and match.get("id"):
        target = f"{match['type']}:{match['id']}"
    else:
        created = client.create_device(device_payload(item))
        item.vigil_device_id = str(created.get("id") or "")
        item.save(update_fields=["vigil_device_id"])
        target = f"{DEVICE_END}:{item.vigil_device_id}"

    _rewrite_links(item, target, user)
    item.delete()
    return target


def _rewrite_links(item, target: str, user) -> None:
    """Point every link touching this item at its Vigil end instead.

    All five fields are unique together, so a rewritten row that already
    exists is deleted rather than updated onto it — and so would a row whose
    two ends became the same thing.
    """
    kind, pk = ITEM_END, str(item.pk)
    # "vigil:device:<id>": the type itself has a colon, so split off the id
    # from the right.
    target_type, target_id = target.rsplit(":", 1)
    with transaction.atomic():
        links = list(
            DynamicLink.objects.filter(source_type=kind, source_id=pk)
            | DynamicLink.objects.filter(target_type=kind, target_id=pk)
        )
        for link in links:
            if link.source_type == kind and link.source_id == pk:
                link.source_type, link.source_id = target_type, target_id
            if link.target_type == kind and link.target_id == pk:
                link.target_type, link.target_id = target_type, target_id
            same_end = link.source_type == link.target_type and link.source_id == link.target_id
            if same_end or _already_there(link):
                link.delete()
                continue
            label = _remote_label(link, user)
            if label is not None:
                link.target_label_cache = label
            link.save()


def _already_there(link) -> bool:
    return DynamicLink.objects.filter(
        source_type=link.source_type,
        source_id=link.source_id,
        target_type=link.target_type,
        target_id=link.target_id,
        relation=link.relation,
    ).exists()


def _remote_label(link, user) -> str | None:
    """The name at a remote end we can still ask for, or None to leave it as it was."""
    if not link.target_type.startswith("vigil:"):
        return None
    target = get_resolver(link.target_type).resolve([link.target_id], user).get(link.target_id)
    return target.label[:200] if target is not None else None


def move_all(user) -> list[tuple[str, str, str]]:
    """Move every device-like item; one that fails does not stop the rest.

    Answers ``(name, "moved"|"failed", detail)`` per item. Anything Vigil
    couldn't do leaves the item where it is — Jackil still has it and its
    links — so running the move again finishes what a down Vigil interrupted.
    """
    items = list(movable_items())
    client = get_client()
    if client is None:
        return [(item.name, "failed", "Vigil is not connected.") for item in items]

    results: list[tuple[str, str, str]] = []
    for item in items:
        try:
            match = suggest_match(client, item)
            target = move_item(client, item, match, user)
        except (VigilUnavailable, SuggestionUnavailable) as failure:
            results.append((item.name, "failed", str(failure)))
            continue
        results.append((item.name, "moved", target))
    return results

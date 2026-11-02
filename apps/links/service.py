"""The links service: what an object's links look like, and how to add or remove one."""

from dataclasses import dataclass

from django.utils import timezone

from .models import DynamicLink
from .registry import LinkTarget, get_resolver
from .relations import DEFAULT_RELATION, RELATIONS, label_for


@dataclass(frozen=True)
class LinkView:
    link_id: int
    relation: str
    label: str  # relation words as seen from the object asked about
    other: LinkTarget


class LinkError(ValueError):
    """Shown to the user; the message is plain words."""


def can_see_links(user) -> bool:
    return getattr(user, "role", None) in ("agent", "admin")


def links_for(type: str, id: str, user) -> list[LinkView]:
    """Every link touching this object that `user` may see, other ends resolved."""
    if not can_see_links(user):
        return []
    as_source = list(DynamicLink.objects.filter(source_type=type, source_id=id))
    as_target = list(DynamicLink.objects.filter(target_type=type, target_id=id))
    if not as_source and not as_target:
        return []

    ids_by_type: dict[str, set[str]] = {}
    for link in as_source + as_target:
        other_type, other_id = _other_end(link, type, id)
        ids_by_type.setdefault(other_type, set()).add(other_id)

    resolved: dict[tuple[str, str], LinkTarget] = {}
    for kind, ids in ids_by_type.items():
        try:
            resolver = get_resolver(kind)
        except KeyError:
            continue
        # One resolve() call per type is what keeps the panel cheap. A type with
        # no resolver cannot answer "may this user see it", so it drops out
        # rather than leaking a name.
        for key, target in resolver.resolve(sorted(ids), user).items():
            resolved[(kind, key)] = target

    views = [
        view
        # A link with this object on both ends lands in both queries and would
        # otherwise be listed twice.
        for link, from_source in [(link, True) for link in as_source]
        + [(link, False) for link in as_target if link.pk not in {each.pk for each in as_source}]
        if (view := _view_for(link, from_source, resolved)) is not None
    ]
    order = list(RELATIONS)
    views.sort(
        key=lambda v: (
            order.index(v.relation) if v.relation in order else len(order),
            v.other.label,
        )
    )
    return views


def add_link(
    user,
    source: tuple[str, str],
    target: tuple[str, str],
    relation: str = DEFAULT_RELATION,
) -> DynamicLink:
    """Create a link after checking both ends exist and the user may see them."""
    if not can_see_links(user):
        raise LinkError("You can't see that.")
    source_type, source_id = source
    target_type, target_id = target
    for kind in (source_type, target_type):
        try:
            get_resolver(kind)
        except KeyError:
            raise LinkError(f"Unknown kind of thing: {kind}") from None
    if relation not in RELATIONS:
        raise LinkError("Unknown kind of link.")
    if source == target:
        raise LinkError("A thing cannot link to itself.")

    resolved = {
        (source_type, source_id): _resolve_one(source_type, source_id, user),
        (target_type, target_id): _resolve_one(target_type, target_id, user),
    }
    if any(t is None for t in resolved.values()):
        raise LinkError("You can't see that.")

    forward = DynamicLink.objects.filter(
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
    )
    backward = DynamicLink.objects.filter(
        source_type=target_type,
        source_id=target_id,
        target_type=source_type,
        target_id=source_id,
    )
    if (forward | backward).filter(relation=relation).exists():
        raise LinkError("Those are already linked.")

    link = DynamicLink(
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relation=relation,
        created_by=user,
    )
    if target_type.startswith("vigil:"):
        link.target_label_cache = resolved[(target_type, target_id)].label[:200]
        link.target_cached_at = timezone.now()
    link.save()
    return link


def remove_link(user, link_id: int) -> None:
    if not can_see_links(user):
        raise LinkError("No such link.")
    link = DynamicLink.objects.filter(pk=link_id).first()
    if link is None:
        raise LinkError("No such link.")
    for kind, obj_id in ((link.source_type, link.source_id), (link.target_type, link.target_id)):
        if _resolve_one(kind, obj_id, user) is None:
            raise LinkError("No such link.")
    link.delete()


def _view_for(
    link: DynamicLink, from_source: bool, resolved: dict[tuple[str, str], LinkTarget]
) -> LinkView | None:
    other_type, other_id = (
        (link.target_type, link.target_id) if from_source else (link.source_type, link.source_id)
    )
    target = resolved.get((other_type, other_id))
    if target is None:
        return None
    if not target.available and link.target_label_cache and link.target_id == other_id:
        target = LinkTarget(
            type=target.type,
            id=target.id,
            label=link.target_label_cache,
            url=target.url,
            status=target.status,
            tone=target.tone,
            available=False,
        )
    return LinkView(
        link_id=link.pk,
        relation=link.relation,
        label=label_for(link.relation, from_source=from_source),
        other=target,
    )


def _other_end(link: DynamicLink, type: str, id: str) -> tuple[str, str]:
    if (link.source_type, link.source_id) == (type, id):
        return link.target_type, link.target_id
    return link.source_type, link.source_id


def _resolve_one(kind: str, obj_id: str, user) -> LinkTarget | None:
    return get_resolver(kind).resolve([obj_id], user).get(obj_id)

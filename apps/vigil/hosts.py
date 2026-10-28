"""An Item's Vigil host, read live and suggested when nothing is linked."""

from django.core.cache import cache

from apps.dashboards.contract import TONES
from apps.links.service import can_see_links
from apps.vigil.client import VigilUnavailable, get_client
from apps.vigil.links import DOWN_KEY, DOWN_SECONDS


def _item(host: dict | None) -> dict | None:
    if not isinstance(host, dict):
        return None
    tone = str(host.get("tone") or "")
    return {
        "id": str(host.get("id") or ""),
        "label": str(host.get("label") or "") or str(host.get("id") or ""),
        "sub": str(host.get("sub") or ""),
        "status": str(host.get("status") or ""),
        "tone": tone if tone in TONES else "",
        "url": str(host.get("url") or ""),
    }


def host_for(item, user) -> dict | None:
    """The live Vigil host an Item is linked to, or None."""
    if not can_see_links(user):
        return None
    if not item.vigil_host_id:
        return None
    client = get_client()
    if client is None or cache.get(DOWN_KEY):
        return None
    try:
        return _item(client.detail("host", item.vigil_host_id))
    except VigilUnavailable as exc:
        cache.set(DOWN_KEY, str(exc), DOWN_SECONDS)
        return None


def _suggestion(host: dict, terms: list[str]) -> bool:
    """A host matches when a term equals its label or one of its sub-line parts."""
    lowered = [term.lower() for term in terms if term]
    if any(term == host["label"].lower() for term in lowered):
        return True
    parts = [part.strip().lower() for part in host["sub"].split(",")]
    return any(term == part for term in lowered for part in parts if part)


def suggest_host(item, user) -> dict | None:
    """A host that looks like this Item, when no host is linked yet."""
    if not can_see_links(user):
        return None
    if item.vigil_host_id:
        return None
    client = get_client()
    if client is None or cache.get(DOWN_KEY):
        return None
    attributes = {k.lower(): str(v) for k, v in (item.attributes or {}).items()}
    terms = [t.strip() for t in (attributes.get("host", ""), attributes.get("ip", ""), item.name)]
    terms = [t for t in terms if t]
    if not terms:
        return None
    try:
        hosts = client.search(terms[0], "host")
    except VigilUnavailable as exc:
        cache.set(DOWN_KEY, str(exc), DOWN_SECONDS)
        return None
    for host in filter(None, (_item(h) for h in hosts)):
        if _suggestion(host, terms):
            return host
    return None

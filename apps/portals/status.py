"""Vigil status-page embeds for a portal home.

Each token in ``Portal.vigil_status_pages`` is read from Vigil's public
status JSON and kept for a minute. Nothing here can break the page: no
connection, a dead Vigil, or a nonsense answer all mean "no embeds".
"""

from django.core.cache import cache

from apps.vigil.client import VigilUnavailable, get_client
from apps.vigil.links import DOWN_KEY, DOWN_SECONDS

CACHE_SECONDS = 60
MAX_PAGES = 10
BAR_STATES = ("up", "degraded", "down", "nodata")


def status_embeds(portal) -> list[dict]:
    """One card's worth of data per listed Vigil status page, in order."""
    tokens = [token for token in (portal.vigil_status_pages or [])[:MAX_PAGES] if token]
    if not tokens:
        return []
    client = get_client()
    if client is None or cache.get(DOWN_KEY):
        return []
    embeds = []
    for token in tokens:
        key = f"portal:status:{token}"
        embed = cache.get(key)
        if embed is None:
            try:
                payload = client.status_page(token)
            except VigilUnavailable as exc:
                cache.set(DOWN_KEY, str(exc), DOWN_SECONDS)
                break
            embed = _embed(payload) if isinstance(payload, dict) else None
            if embed is None:
                continue
            cache.set(key, embed, CACHE_SECONDS)
        embeds.append(embed)
    return embeds


def _embed(payload):
    """Only the fields the card renders; None when the answer isn't a page."""
    if not all(field in payload for field in ("all_up", "up_count", "total")):
        return None
    hosts = payload.get("hosts")
    if not isinstance(hosts, list):
        return None
    down = _as_int(payload["total"]) - _as_int(payload["up_count"])
    return {
        "all_up": bool(payload["all_up"]),
        "up_count": payload["up_count"],
        "total": payload["total"],
        "headline": _headline(payload, down),
        "hosts": _hosts(hosts),
    }


def _headline(payload, down):
    if payload["all_up"]:
        return "All systems up"
    return f"{down} of {_as_int(payload['total'])} services down"


def _hosts(hosts):
    cleaned = []
    for host in hosts:
        if not isinstance(host, dict) or "hostname" not in host:
            continue
        cleaned.append(
            {
                "hostname": str(host["hostname"]),
                "up": bool(host.get("up")),
                "uptime_pct": str(host.get("uptime_pct") or ""),
                "bars": _bars(host.get("bars")),
            }
        )
    return cleaned


def _bars(bars):
    if not isinstance(bars, list):
        return []
    clean = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        state = str(bar.get("state") or "")
        clean.append(
            {
                "state": state if state in BAR_STATES else "nodata",
                "label": str(bar.get("label") or ""),
            }
        )
    return clean


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

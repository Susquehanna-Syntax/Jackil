"""Real resolvers for the five ``vigil:*`` link types."""

from django.core.cache import cache

from apps.dashboards.contract import TONES
from apps.links.registry import LinkTarget, Resolver, register_type
from apps.links.service import can_see_links
from apps.vigil.client import TYPES, VigilUnavailable, get_client
from apps.vigil.models import VigilConnection

DOWN_KEY = "vigil:down"
DOWN_SECONDS = 30
SEARCH_SECONDS = 30

#: Deep links look like "<base_url>/#open/<type>/<id>".
OPEN_PREFIX = "/#open/"


def _unavailable(kind: str, id_: str, status: str) -> LinkTarget:
    return LinkTarget(
        type=kind,
        id=id_,
        label=id_,
        status=status,
        tone="muted",
        available=False,
    )


def _target(kind: str, id_: str, item: dict) -> LinkTarget:
    tone = str(item.get("tone") or "")
    return LinkTarget(
        type=kind,
        id=id_,
        label=str(item.get("label") or ""),
        url=str(item.get("url") or ""),
        status=str(item.get("status") or ""),
        tone=tone if tone in TONES else "",
    )


class VigilResolver(Resolver):
    """One ``vigil:<kind>`` type, answered live from the Vigil client."""

    def __init__(self, kind: str):
        self.kind = kind

    @property
    def link_type(self) -> str:
        return f"vigil:{self.kind}"

    def resolve(self, ids: list[str], user) -> dict[str, LinkTarget]:
        if not can_see_links(user):
            return {}
        client = get_client()
        if client is None:
            return {i: _unavailable(self.link_type, i, "Vigil not connected") for i in ids}
        if cache.get(DOWN_KEY):
            return {i: _unavailable(self.link_type, i, "Vigil unavailable") for i in ids}
        try:
            items = client.resolve(self.kind, ids)
        except VigilUnavailable as exc:
            cache.set(DOWN_KEY, str(exc), DOWN_SECONDS)
            return {i: _unavailable(self.link_type, i, "Vigil unavailable") for i in ids}
        return {
            i: _target(self.link_type, i, items[i]) for i in ids if isinstance(items.get(i), dict)
        }

    def search(self, q: str, user, limit: int) -> list[LinkTarget]:
        if not can_see_links(user):
            return []
        client = get_client()
        if client is None or cache.get(DOWN_KEY):
            return []
        key = f"vigil:search:{q.lower()}"
        results = cache.get(key)
        if results is None:
            try:
                results = client.search(q)
            except VigilUnavailable as exc:
                cache.set(DOWN_KEY, str(exc), DOWN_SECONDS)
                return []
            cache.set(key, results, SEARCH_SECONDS)
        mine = [item for item in results if item.get("type") == self.kind][:limit]
        return [_target(self.link_type, str(item.get("id", "")), item) for item in mine]

    def from_url(self, url: str) -> str | None:
        base_url = VigilConnection.get_solo().base_url
        if not base_url:
            return None
        marker = f"{OPEN_PREFIX}{self.kind}/"
        if not (url.startswith(base_url) and marker in url):
            return None
        id_ = url.split(marker, 1)[1]
        return id_.split("#", 1)[0] or None


def register_vigil_types() -> None:
    for kind in TYPES:
        register_type(f"vigil:{kind}", VigilResolver(kind))

"""The registry: how each app says its objects can be named, found and authorised."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LinkTarget:
    type: str
    id: str
    label: str
    url: str = ""
    status: str = ""
    tone: str = ""  # one of apps.dashboards.contract.TONES, or ""
    available: bool = True


class Resolver:
    """How one object type is named, found and authorised. Subclass per type."""

    def resolve(self, ids: list[str], user) -> dict[str, LinkTarget]:
        """Targets for the ids this user may see. Missing or hidden ids are absent."""
        raise NotImplementedError

    def search(self, q: str, user, limit: int) -> list[LinkTarget]:
        raise NotImplementedError

    def from_url(self, url: str) -> str | None:
        """The id if `url` points at one of this type's objects, else None."""
        return None


_TYPES: dict[str, Resolver] = {}


def register_type(name: str, resolver: Resolver) -> None:
    """Register (or replace) the resolver for a type name.

    Replacement is deliberate: a later milestone swaps the ``vigil:*`` stubs
    for real resolvers under the same names.
    """
    _TYPES[name] = resolver


def get_resolver(name: str) -> Resolver:
    return _TYPES[name]


def types() -> list[str]:
    """Registered type names, sorted."""
    return sorted(_TYPES)

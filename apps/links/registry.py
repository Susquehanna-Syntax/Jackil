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
    #: Extra label/value pairs for the picker's preview pane. A tuple so
    #: instances stay hashable.
    facts: tuple[tuple[str, str], ...] = ()
    excerpt: str = ""


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

    def available(self, user) -> bool:
        """False while this type's source cannot answer (Vigil down or not connected)."""
        return True

    def recent(self, user, limit: int) -> list[LinkTarget]:
        """What the picker lists before anything is typed. Default: nothing."""
        return []

    def preview(self, id: str, user) -> LinkTarget | None:
        """One target with facts and an excerpt, for the picker's preview pane."""
        return self.resolve([id], user).get(id)


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


#: What a person calls each type: the picker groups results under these words
#: rather than the stored names ("card", "vigil:host").
TYPE_LABELS = {
    "ticket": "Tickets",
    "card": "Issues",
    "project": "Projects",
    "page": "Wiki pages",
    "item": "Dynamic Items",
}

#: The picker's tab colours; anything unlisted falls back to ``"all"``.
TYPE_COLOURS: dict[str, str] = {
    "vigil:host": "sky",
    "vigil:device": "peach",
    "ticket": "rose",
    "page": "lav",
    "card": "mint",
    "project": "mint",
    "item": "lemon",
}

#: Tab order in the picker. ``vigil:device`` is M17's; naming it here means
#: that milestone only has to register the type.
PICKER_ORDER = ["vigil:host", "vigil:device", "ticket", "page", "card", "project", "item"]


def type_label(name: str) -> str:
    """The plural, human name for a type; Vigil kinds read "Vigil hosts" etc."""
    if name in TYPE_LABELS:
        return TYPE_LABELS[name]
    if name.startswith("vigil:"):
        return "Vigil " + name.split(":", 1)[1] + "s"
    return name.replace("_", " ").capitalize()


def type_colour(name: str) -> str:
    return TYPE_COLOURS.get(name, "all")


def picker_types() -> list[str]:
    """Registered types in the picker's tab order, then whatever else is registered."""
    registered = types()
    ordered = [name for name in PICKER_ORDER if name in registered]
    rest = sorted(name for name in registered if name not in PICKER_ORDER)
    return ordered + rest

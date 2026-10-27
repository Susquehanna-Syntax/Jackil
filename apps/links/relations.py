"""Dynamic Links — the fixed set of ways one thing can point at another."""

#: slug -> (label from the source's side, label from the target's side)
RELATIONS: dict[str, tuple[str, str]] = {
    "relates_to": ("relates to", "relates to"),
    "affects": ("affects", "affected by"),
    "caused_by": ("caused by", "caused"),
    "fixed_by": ("fixed by", "fixes"),
    "documented_in": ("documented in", "documents"),
    "part_of": ("part of", "contains"),
    "blocks": ("blocks", "blocked by"),
    "duplicates": ("duplicates", "duplicated by"),
}
DEFAULT_RELATION = "relates_to"


def label_for(relation: str, from_source: bool) -> str:
    """The words for a relation as seen from one end."""
    return RELATIONS[relation][0 if from_source else 1]

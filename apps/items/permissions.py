def can_view_items(user) -> bool:
    return getattr(user, "role", None) in ("agent", "admin")


def can_edit_items(user) -> bool:
    """Agents and admins create and edit Items."""
    return getattr(user, "role", None) in ("agent", "admin")


def can_delete_items(user) -> bool:
    return getattr(user, "role", None) == "admin"


def can_manage_kinds(user) -> bool:
    return getattr(user, "role", None) == "admin"

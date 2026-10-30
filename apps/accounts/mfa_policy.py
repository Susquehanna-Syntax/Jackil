"""Who must show a second factor at sign-in: Jackil's staff, not customers."""


def required(user) -> bool:
    role = getattr(user, "role", "")
    return bool(getattr(user, "is_active", False) and role in ("agent", "admin"))

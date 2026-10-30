"""Who must show a second factor. The rule is a dotted path in settings
(``MFA_REQUIRED``) because Civil, Mercantil and Jackil will not agree on it."""


def everyone(user) -> bool:
    """Every account that can sign in at all."""
    return bool(getattr(user, "is_active", False))


def staff_only(user) -> bool:
    """Only the people who run the system. Jackil swaps in a role check."""
    return bool(getattr(user, "is_active", False) and getattr(user, "is_staff", False))

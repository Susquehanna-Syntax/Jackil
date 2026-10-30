"""One-time recovery codes: the way in when the phone is gone."""

import secrets

from django.contrib.auth.hashers import check_password
from django.utils.timezone import now

from .models import RecoveryCode
from .totp import _clear_totp_attempts, _totp_attempt_allowed

RECOVERY_CODE_COUNT = 10
#: No vowels, no l/i/1/o/0 — a code transcribed off paper reads right.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_CODE_LENGTH = 10


def _new_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


def format_code(plain: str) -> str:
    return f"{plain[:5]}-{plain[5:]}"


def normalise(code: str) -> str:
    """What the user typed, reduced to what is actually compared. The hash is
    of this form, so a code read off paper in capitals or with the dash left
    out still works."""
    return (code or "").strip().lower().replace(" ", "").replace("-", "")


def looks_like_recovery_code(code: str) -> bool:
    """A typed code is tried as a recovery code when it has a dash in it or
    is longer than six characters. Six digits always stay TOTP."""
    raw = (code or "").strip().replace(" ", "")
    return "-" in raw or len(normalise(raw)) >= 7


def make_codes(user) -> list[str]:
    """Replace the user's recovery codes with ``RECOVERY_CODE_COUNT`` new
    ones. Returns the plain codes — shown once, never stored unhashed."""
    RecoveryCode.objects.filter(user=user).delete()
    plains = [format_code(_new_code()) for _ in range(RECOVERY_CODE_COUNT)]
    for plain in plains:
        RecoveryCode.new(user, normalise(plain))
    return plains


def use_code(user, code: str) -> bool:
    """Spend the first unused recovery code matching ``code``.

    Guesses count against the same per-user limit as TOTP codes.
    """
    typed = normalise(code)
    if not typed or not _totp_attempt_allowed(user):
        return False
    candidate = next(
        (c for c in RecoveryCode.objects.filter(user=user, used_at__isnull=True)
         if check_password(typed, c.code_hash)),
        None,
    )
    if candidate is None:
        return False
    # Spent by a conditional UPDATE, so two requests racing on one code cannot
    # both get in with it.
    spent = RecoveryCode.objects.filter(pk=candidate.pk, used_at__isnull=True).update(used_at=now())
    if spent != 1:
        return False
    _clear_totp_attempts(user)
    return True


def remaining(user) -> int:
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()

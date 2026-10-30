"""RFC 6238 TOTP, implemented inline to avoid a pyotp dependency.

Secrets are base32-encoded (RFC 3548). SHA-1, 6 digits, 30-second step —
matching every authenticator app in common use (Google Authenticator,
1Password, Authy, Bitwarden, Aegis…). Ported from Vigil's working copy.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from datetime import timedelta
from urllib.parse import quote

from django.utils.timezone import now

from .conf import issuer
from .models import MfaProfile, TotpAttempt

_STEP_SECONDS = 30
_DIGITS = 6


def generate_secret(length_bytes: int = 20) -> str:
    """Return a fresh base32-encoded secret (default: 160 bits, per RFC 4226)."""
    raw = os.urandom(length_bytes)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    # Re-pad to a multiple of 8 so base32decode accepts it.
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (
        ((digest[offset] & 0x7F) << 24)
        | ((digest[offset + 1] & 0xFF) << 16)
        | ((digest[offset + 2] & 0xFF) << 8)
        | (digest[offset + 3] & 0xFF)
    )
    return str(code_int % (10 ** _DIGITS)).zfill(_DIGITS)


def generate_totp(secret_b32: str, at: float | None = None) -> str:
    counter = int((at if at is not None else time.time()) // _STEP_SECONDS)
    return _hotp(secret_b32, counter)


def verify_totp(secret_b32: str, code: str, window: int = 1) -> bool:
    """Constant-time compare of ``code`` against the current TOTP, ±window steps."""
    if not secret_b32 or not code:
        return False
    code = code.strip().replace(" ", "")
    if len(code) != _DIGITS or not code.isdigit():
        return False
    now_step = int(time.time() // _STEP_SECONDS)
    for drift in range(-window, window + 1):
        candidate = _hotp(secret_b32, now_step + drift)
        if hmac.compare_digest(candidate, code):
            return True
    return False


def otpauth_uri(secret_b32: str, account_name: str, issuer_name: str | None = None) -> str:
    """Return the ``otpauth://`` URI you can stuff into a QR code."""
    name = issuer_name or issuer()
    label = quote(f"{name}:{account_name}")
    params = (
        f"secret={secret_b32}&issuer={quote(name)}"
        f"&algorithm=SHA1&digits={_DIGITS}&period={_STEP_SECONDS}"
    )
    return f"otpauth://totp/{label}?{params}"


# A code is valid for up to (1 step + window) before and after the current
# step. With window=1 and step=30s that's a 90-second total validity window,
# which is also how long we treat a freshly-consumed code as "burned".
_REPLAY_WINDOW_SECONDS = (2 * 1 + 1) * _STEP_SECONDS

#: Wrong codes allowed per user inside the window before TOTP-gated actions
#: are refused for the rest of it.
MAX_TOTP_FAILURES = 5
TOTP_FAILURE_WINDOW_MINUTES = 10


def _totp_attempt_allowed(user) -> bool:
    """Record this attempt, then say whether it is within the limit.

    Recorded first and counted after, so requests racing each other each see
    the others' rows: checking and recording in the other order let a burst of
    parallel guesses all pass a check that none of them had yet incremented.

    A guess older than ``TOTP_FAILURE_WINDOW_MINUTES`` stops counting, so a
    lock-out clears on its own without anyone having to wait for the last
    failure to age out. The rows themselves live longer than that — 24 hours —
    because the window has to be measured from *rows*, not from wall-clock
    arithmetic on a timestamp: an interval built one way and compared against
    another silently counts everything, or nothing.
    """
    from django.utils.timezone import now as tz_now

    TotpAttempt.objects.create(user=user)
    stale = tz_now() - timedelta(minutes=TOTP_FAILURE_WINDOW_MINUTES)
    TotpAttempt.objects.filter(created_at__lt=stale).delete()
    TotpAttempt.objects.filter(created_at__lt=tz_now() - timedelta(hours=24)).delete()
    return TotpAttempt.objects.filter(user=user).count() <= MAX_TOTP_FAILURES


def _clear_totp_attempts(user) -> None:
    TotpAttempt.objects.filter(user=user).delete()


def consume_totp(user, code: str, request=None) -> tuple[bool, str | None]:
    """Verify a TOTP code for ``user`` and mark it consumed.

    Rejects codes that were used within the validity window so an
    intercepted code cannot be replayed for a second sensitive action.
    A ``wa_…`` key token — handed back by a security-key tap, never typed —
    is accepted here too, which is what lets every gate below be confirmed
    with a key instead of a code. Returns ``(ok, error_message)``.
    """
    from .keys import KEY_TOKEN_PREFIX, consume_key_token
    from .recovery import looks_like_recovery_code, use_code

    code = (code or "").strip().replace(" ", "")
    if code.startswith(KEY_TOKEN_PREFIX):
        # Key tokens live in the browser's session, so only a caller that
        # passes the request can spend one.
        if request is not None and consume_key_token(request, user, code):
            return True, None
        return False, "That key confirmation expired. Tap your key again."
    if looks_like_recovery_code(code):
        if use_code(user, code):
            return True, None
        return False, ("That recovery code doesn't exist or has already been used. "
                       "Codes are not case-sensitive and the dash is optional.")
    profile = getattr(user, "mfa", None)
    secret = profile.totp_secret if profile else ""
    if not (profile is not None and profile.confirmed()):
        return False, "No authenticator is set up for this account yet."

    if not code:
        return False, "Enter the six-digit code from your authenticator app."
    # A six-digit code falls to guessing without a limit, and the gate exists
    # for exactly the case where someone holds a session but not the device.
    if not _totp_attempt_allowed(user):
        return False, "Too many wrong codes. Wait a few minutes and try again."
    if not verify_totp(secret, code):
        return False, "That code didn't match. Check your authenticator's clock and try again."
    _clear_totp_attempts(user)

    # Spend the code with one conditional UPDATE: of two requests racing on the
    # same code, the database lets exactly one change the row.
    from datetime import timedelta

    from .models import MfaProfile

    spent_at = now()
    cutoff = spent_at - timedelta(seconds=_REPLAY_WINDOW_SECONDS)
    updated = (
        MfaProfile.objects.filter(pk=profile.pk)
        .exclude(last_totp_code=code, last_totp_used_at__gte=cutoff)
        .update(last_totp_code=code, last_totp_used_at=spent_at)
    )
    if updated != 1:
        return False, "That code was already used. Wait for the next one."
    profile.last_totp_code = code
    profile.last_totp_used_at = spent_at
    return True, None


def has_second_factor(user) -> bool:
    """Whether this account can answer a second-factor prompt at all: a
    confirmed TOTP, or at least one security key."""
    if user.security_keys.exists():
        return True
    profile = getattr(user, "mfa", None)
    return bool(profile is not None and profile.confirmed())


def confirm_secret(user, secret: str, code: str) -> tuple[bool, str | None]:
    """Confirm a pending enrolment secret with the user's first code.

    The old secret — if any — stays in place until the new one checks out,
    so a mistyped or scanned-wrong key never locks anyone out.
    """
    code = (code or "").strip().replace(" ", "")
    if not _totp_attempt_allowed(user):
        return False, "Too many wrong codes. Wait a few minutes and try again."
    if not (secret and verify_totp(secret, code)):
        return False, "That code didn't match. Check your authenticator's clock and try again."
    _clear_totp_attempts(user)
    profile, _ = MfaProfile.objects.get_or_create(user=user)
    profile.totp_secret = secret
    profile.totp_confirmed_at = now()
    # The code that confirmed enrolment is spent, as any other is.
    profile.last_totp_code = code
    profile.last_totp_used_at = now()
    profile.save()
    return True, None

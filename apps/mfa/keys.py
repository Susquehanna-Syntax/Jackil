"""WebAuthn / FIDO2 security keys and passkeys. Ported from Vigil's working
``webauthn_keys.py``.

Options, ceremony verification, and the one-time key token that lets a key tap
stand in for a six-digit code at every existing confirmation gate.

Shape of the exchange:

  register:  POST options  → session["mfa_webauthn_reg"] = {challenge, exp}
             POST credential → verify against that challenge → SecurityKey row

  assert:    POST options  → session["mfa_webauthn_auth"] = {challenge, exp}
             POST credential → verify → wa_… token cached against the user id

``consume_totp`` recognises the ``wa_`` prefix and hands it to
``consume_key_token``, which is single-use by construction: the token is only
accepted by the request that manages to ``cache.delete`` it. The token is
stored hashed — a cache dump alone must not hand over a live factor.

The identity a key is bound to comes from ``MFA_PUBLIC_URL`` and never from a
request header. An *assertion* may additionally be checked against the origins
the caller lists (see ``allowed_origins``), because a page served over one host
is where its own ceremony runs; registration is always the configured origin
alone, so no header can enrol a key for a domain nobody configured.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit

from django.utils.timezone import now
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from . import conf

#: A key token is a stand-in for a code, so it lives about as long as one.
KEY_TOKEN_PREFIX = "wa_"
KEY_TOKEN_SECONDS = 60
#: Long enough for a slow authenticator or a phone that has to wake up.
CHALLENGE_SECONDS = 120

REG_SESSION_KEY = "mfa_webauthn_reg"
AUTH_SESSION_KEY = "mfa_webauthn_auth"


TOKEN_SESSION_KEY = "mfa:key_tokens"


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def relying_party(request) -> tuple[str, str]:
    """(rp id, origin) — the two values the browser and we must agree on.

    Only ever ``MFA_PUBLIC_URL``: the identity a key is bound to comes from
    configuration, never from a request header. Without it this returns
    ``("", "")`` and security keys are unavailable (see ``unavailable_reason``).
    ``request`` is accepted for the callers' convenience and not read.
    """
    public = conf.public_url().strip().rstrip("/")
    if not public:
        return "", ""
    split = urlsplit(public if "//" in public else f"https://{public}")
    host = split.hostname or ""
    scheme = split.scheme or "https"
    port = f":{split.port}" if split.port else ""
    return host, f"{scheme}://{host}{port}"


def rp_name() -> str:
    """The name an authenticator shows next to the account it belongs to."""
    return conf.rp_name()


def secure_context(origin: str) -> bool:
    """WebAuthn only runs where the browser will run it: https, or localhost."""
    if not origin:
        return False
    split = urlsplit(origin)
    host = split.hostname or ""
    if split.scheme == "https":
        return True
    return split.scheme == "http" and (
        host in ("localhost", "127.0.0.1") or host.endswith(".localhost")
    )


def unavailable_reason(origin: str) -> str:
    """Why security keys cannot be used here, or "" when they can."""
    if not origin:
        return (
            "Set MFA_PUBLIC_URL to the address you open this site at to use "
            "security keys."
        )
    if not secure_context(origin):
        return "Security keys need HTTPS."
    return ""


def _required_party(request) -> tuple[str, str]:
    """The relying party, or a ValueError saying why keys are unavailable."""
    rp_id, origin = relying_party(request)
    reason = unavailable_reason(origin)
    if reason:
        raise ValueError(reason)
    return rp_id, origin


def _store_challenge(session, key: str, challenge: bytes) -> None:
    session[key] = {
        "challenge": bytes_to_base64url(challenge),
        "exp": time.time() + CHALLENGE_SECONDS,
    }


def _take_challenge(session, key: str) -> bytes:
    """The stored challenge, once. Reading it removes it."""
    pending = session.get(key) or {}
    session.pop(key, None)
    challenge = pending.get("challenge") or ""
    exp = pending.get("exp") or 0
    if not challenge or time.time() >= exp:
        raise ValueError("The key request expired. Start again.")
    return base64url_to_bytes(challenge)


def registration_options(request) -> dict:
    """Creation options, with the user's existing keys excluded so an already
    enrolled authenticator cannot silently be enrolled twice.

    The rp id is in the JSON (``rpId``); the origin is added too, since a
    browser takes it from where the page was served and this tells it which
    identity we will verify against.
    """
    from .models import SecurityKey

    rp_id, origin = _required_party(request)
    # The same bytes go to the browser and into the session: verification
    # compares what the authenticator signed against exactly this.
    challenge = secrets.token_bytes(32)
    _store_challenge(request.session, REG_SESSION_KEY, challenge)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name(),
        user_name=request.user.get_username(),
        user_id=str(request.user.pk).encode(),
        user_display_name=request.user.get_username(),
        challenge=challenge,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(key.credential_id))
            for key in SecurityKey.objects.filter(user=request.user)
        ],
    )
    result = json.loads(options_to_json(options))
    result["rpId"] = rp_id
    result["origin"] = origin
    return result


def allowed_origins(request, configured: str, extra=()) -> list[str]:
    """Origins an assertion may come from: the configured one plus any the
    caller adds (the page's own), each a well-formed absolute origin."""
    origins = [configured] if configured else []
    for candidate in extra:
        well_formed = isinstance(candidate, str) and candidate.startswith(
            ("https://", "http://")
        )
        if well_formed and candidate not in origins:
            origins.append(candidate)
    return origins


def user_has_keys(user) -> bool:
    """Whether this account has a key to tap. An anonymous visitor has none."""
    return bool(getattr(user, "is_authenticated", False)) and user.security_keys.exists()


def _clean_name(raw) -> str:
    name = (raw or "").strip() if isinstance(raw, str) else ""
    if not 1 <= len(name) <= 60:
        raise ValueError("Give the key a name of 1 to 60 characters.")
    return name


def authentication_options(request, user=None) -> dict:
    """Request options listing this user's keys, so the browser can offer
    exactly the authenticators that can satisfy them.

    ``user`` is the signed-in user unless given: the sign-in page passes the
    account whose password was just accepted, before anyone is signed in. The
    stored transports go on each allowed credential — a passkey kept on the
    device needs that hint, or a laptop with no reader offers nothing at all.
    """
    from .models import SecurityKey

    user = user if user is not None else request.user
    if not user_has_keys(user):
        raise ValueError("No security key is set up for this account.")
    keys = list(SecurityKey.objects.filter(user=user))
    rp_id, _origin = _required_party(request)
    challenge = secrets.token_bytes(32)
    _store_challenge(request.session, AUTH_SESSION_KEY, challenge)
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        allow_credentials=[
            PublicKeyCredentialDescriptor(
                id=bytes(key.credential_id), transports=_transports(key.transports)
            )
            for key in keys
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    result = json.loads(options_to_json(options))
    result["rpId"] = rp_id
    return result


def _transports(raw) -> list[AuthenticatorTransport]:
    """The stored transport names, keeping only the ones a browser may be
    told about; an empty list means "any", which is what an unrecorded key is."""
    known = {t.value: t for t in AuthenticatorTransport}
    names = raw if isinstance(raw, list) else []
    return [known[name] for name in names if name in known]


def _credential_id(credential) -> bytes:
    """The authenticator's raw credential id, however the client spelled it.

    ``rawId`` is what the WebAuthn spec puts on the response object; the JSON
    we build carries both, and a hand-made credential may carry only one.
    """
    if not isinstance(credential, dict):
        raise TypeError("The credential must be an object.")
    raw = credential.get("id") or credential.get("rawId")
    if not raw:
        raise ValueError("The credential is missing its id.")
    return base64url_to_bytes(raw)


def _credential_transports(credential) -> list[str]:
    response = credential.get("response") if isinstance(credential, dict) else None
    raw = response.get("transports") if isinstance(response, dict) else None
    if not isinstance(raw, list):
        return []
    return [str(t) for t in raw][:8]


def register(request, name, credential):
    """Verify a registration response against the session challenge and save."""
    from .models import SecurityKey

    rp_id, origin = _required_party(request)
    expected = _take_challenge(request.session, REG_SESSION_KEY)
    label = _clean_name(name)
    verified = verify_registration_response(
        credential=credential,
        expected_challenge=expected,
        expected_rp_id=rp_id,
        expected_origin=origin,
    )
    return SecurityKey.objects.create(
        user=request.user,
        name=label,
        credential_id=bytes(verified.credential_id),
        public_key=bytes(verified.credential_public_key),
        sign_count=verified.sign_count,
        transports=_credential_transports(credential),
    )


def authenticate(request, credential, user=None) -> str:
    """Verify an assertion and issue a one-time key token for it.

    The credential is looked up among *this* user's keys only: a token must
    never be issuable by presenting somebody else's authenticator.
    """
    from .models import SecurityKey

    user = user if user is not None else request.user
    rp_id, configured = _required_party(request)
    expected = _take_challenge(request.session, AUTH_SESSION_KEY)
    raw_id = _credential_id(credential)
    key = SecurityKey.objects.filter(user=user, credential_id=raw_id).first()
    if key is None:
        raise ValueError("That security key is not set up for this account.")
    verified = verify_authentication_response(
        credential=credential,
        expected_challenge=expected,
        expected_rp_id=rp_id,
        # Only the configured origin: a request header is the one thing a
        # proxy in the middle gets to choose.
        expected_origin=configured,
        credential_public_key=bytes(key.public_key),
        credential_current_sign_count=key.sign_count,
    )
    key.sign_count = verified.new_sign_count
    key.last_used_at = now()
    key.save(update_fields=["sign_count", "last_used_at"])

    from .models import KeyToken

    token = KEY_TOKEN_PREFIX + secrets.token_urlsafe(32)
    # A database row (shared by every server worker), bound to this user and
    # this browser's session, spent by an atomic delete.
    KeyToken.objects.filter(expires_at__lt=now()).delete()
    KeyToken.objects.create(
        digest=_token_digest(token),
        user=user,
        session_key=_session_key(request),
        expires_at=now() + timedelta(seconds=KEY_TOKEN_SECONDS),
    )
    return token


def _session_key(request) -> str:
    session = request.session
    if not getattr(session, "session_key", None) and hasattr(session, "save"):
        session.save()
    return getattr(session, "session_key", "") or ""


def consume_key_token(request, user, token: str) -> bool:
    """True exactly once, for the user and browser session it was issued to."""
    from .models import KeyToken

    if not isinstance(token, str) or not token.startswith(KEY_TOKEN_PREFIX):
        return False
    deleted, _ = KeyToken.objects.filter(
        digest=_token_digest(token),
        user=user,
        session_key=_session_key(request),
        expires_at__gt=now(),
    ).delete()
    return deleted == 1

"""Reading a signed SQSY licence blob: format, signature, claims.

The blob is ``SQSY-LICENSE-V1.<b64url payload>.<b64url signature>``, with
base64url *without* padding and the signature being Ed25519 over the exact
payload bytes. Verification here is cryptographic only — expiry and binding to
a Vigil instance are policy decisions ``service.py`` makes afterwards, because
a genuine expired licence still verifies.
"""

import base64
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PREFIX = "SQSY-LICENSE-V1"


class LicenceError(Exception):
    """The licence could not be read or was not genuine; str is a plain reason."""


@dataclass(frozen=True)
class Claims:
    instance: str
    org: str
    seats: int
    exp: int
    iat: int
    sites: int | None
    lid: str
    features: tuple[str, ...]

    @property
    def expiry_date(self):
        """``exp`` as a UTC datetime, or None when there is none to show."""
        import datetime

        if not self.exp:
            return None
        try:
            return datetime.datetime.fromtimestamp(self.exp, tz=datetime.UTC)
        except (OverflowError, OSError, ValueError):
            return None


def verify_blob(blob: str, public_key_b64: str) -> Claims:
    """The licence claims signed under ``public_key_b64``; LicenceError if not."""
    blob = str(blob or "").strip()
    if not blob:
        raise LicenceError("There is no licence blob to check.")
    if not public_key_b64:
        raise LicenceError("Jackil has no SQSY signing key to check the licence with.")

    parts = blob.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenceError(f"The licence is not in the {PREFIX} format.")
    payload_part, signature_part = parts[1], parts[2]

    try:
        payload_bytes = _unb64u(payload_part)
        signature = _unb64u(signature_part)
    except (ValueError, base64.binascii.Error):
        raise LicenceError("The licence is not properly encoded.") from None

    key = _public_key(public_key_b64)
    try:
        key.verify(signature, payload_bytes)
    except InvalidSignature:
        raise LicenceError("The licence signature does not match SQSY's signing key.") from None

    return _claims(payload_bytes)


def _public_key(public_key_b64: str) -> Ed25519PublicKey:
    unusable = LicenceError("Jackil's SQSY signing key is not a usable key.")
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except (ValueError, base64.binascii.Error):
        raise unusable from None
    if len(raw) != 32:
        raise unusable
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError:
        raise unusable from None


def _claims(payload_bytes: bytes) -> Claims:
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise LicenceError("The licence payload could not be read.") from None
    if not isinstance(payload, dict):
        raise LicenceError("The licence payload could not be read.")

    features = payload.get("features")
    if features is None:
        # Absent features means "every Business feature" (Vigil's convention),
        # and Vigil's Business set includes "jackil" — so a licence that lists
        # nothing grants Jackil. Jackil's own slugs ride along for display.
        from apps.licensing.service import BUSINESS_FEATURES

        claimed = tuple(sorted(BUSINESS_FEATURES | {"jackil"}))
    elif isinstance(features, list):
        claimed = tuple(str(feature) for feature in features)
    else:
        raise LicenceError("The licence feature list could not be read.")

    sites = payload.get("sites")
    return Claims(
        instance=_text(payload.get("instance")),
        org=_text(payload.get("org")),
        seats=_number(payload.get("seats")),
        exp=_number(payload.get("exp")),
        iat=_number(payload.get("iat")),
        sites=sites if isinstance(sites, int) and not isinstance(sites, bool) else None,
        lid=_text(payload.get("lid")),
        features=claimed,
    )


def _text(value) -> str:
    return str(value) if value is not None else ""


def _number(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LicenceError("The licence dates could not be read.")
    return int(value)


def _unb64u(part: str) -> bytes:
    pad = "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(part + pad)

"""What edition Jackil is running, worked out from the linked Vigil's licence.

Jackil never trusts Vigil's verdict — only SQSY's signature. The stored record
is classified on every read, so a dropped Vigil link keeps the last good
licence for ``GRACE_DAYS`` before Business switches off. Nothing here may
break a page: every public function catches its own errors and answers "free".
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.vigil.client import VigilUnavailable, get_client

from .models import LicenceRecord
from .verify import Claims, LicenceError, verify_blob

GRACE_DAYS = 14
REFRESH_SECONDS = 3600
CACHE_SECONDS = 60
BUSINESS_FEATURES = frozenset(
    {
        "portal_branding",
        "saml",
        "csv_export",
        "audit_log",
        "csat",
        "white_label",
    }
)

EDITION_KEY = "licensing:edition"


@dataclass(frozen=True)
class Edition:
    status: str  # none|valid|grace|lapsed|invalid|mismatch|not_included|unlinked
    claims: Claims | None = None
    detail: str = ""

    @property
    def business(self) -> bool:
        return self.status in ("valid", "grace")


def refresh() -> Edition:
    """Fetch the licence from Vigil now, store it, and classify what was stored."""
    try:
        _fetch_from_vigil()
        edition = _classify(LicenceRecord.get_solo())
    except Exception:
        # Licensing never breaks a page; answer free.
        edition = Edition("none", detail="Jackil could not check the licence.")
    _store(edition)
    return edition


def current() -> Edition:
    """The edition, from the stored record; goes back to Vigil when stale.

    The record is asked first and never overridden by a guess: if it still
    says Business, that stands even when Vigil cannot be reached now. Going
    back to Vigil happens when the answer has gone stale, or when the record
    cannot answer at all — no row yet, or a licence sitting there that has
    never verified against any key (so there is no ``last_verified_at`` to
    judge a dropped link by).
    """
    from django.core.cache import cache

    cached = cache.get(EDITION_KEY)
    if isinstance(cached, Edition):
        return cached
    try:
        record = LicenceRecord.objects.filter(pk=1).first()
        if record is None or _is_stale(record):
            edition = refresh()
        else:
            edition = _classify(record)
            # A blob that does not verify *here* says nothing about the edition;
            # it may predate a signing-key change. Let Vigil answer, and let a
            # Vigil Jackil cannot reach leave the stored licence standing.
            if record.last_verified_at is None and edition.status in (
                "invalid",
                "mismatch",
                "not_included",
                "unlinked",
            ):
                edition = refresh()
    except Exception:
        edition = Edition("none", detail="Jackil could not check the licence.")
    _store(edition)
    return edition


def business_active() -> bool:
    """Is SQSY Business on right now?"""
    try:
        return current().business
    except Exception:
        return False


def has_feature(slug: str) -> bool:
    """True when ``slug`` is a Business feature the licence grants.

    Which slugs a Business licence carries is SQSY's decision, not Jackil's, so
    every Business slug is on once the edition is Business. The licence's own
    ``features`` list still has to name Jackil — that is what classifies the
    edition in the first place (see ``_classify``).

    ``BUSINESS_FEATURES`` is checked without importing anything, so a slug that
    is not a Business feature never touches the licensing machinery.
    """
    if slug not in BUSINESS_FEATURES:
        return False
    try:
        return current().business
    except Exception:
        return False


# ── internals ───────────────────────────────────────────────────────────────


def _store(edition: Edition) -> None:
    from django.core.cache import cache

    cache.set(EDITION_KEY, edition, CACHE_SECONDS)


def _is_stale(record: LicenceRecord) -> bool:
    if record.last_checked_at is None:
        return True
    return (timezone.now() - record.last_checked_at).total_seconds() > REFRESH_SECONDS


def _fetch_from_vigil():
    record = LicenceRecord.get_solo()
    client = get_client()
    if client is None:
        record.last_error = "Vigil is not connected."
    else:
        try:
            answer = client.licence()
        except VigilUnavailable as exc:
            record.last_error = str(exc)[:300]
        except Exception:
            record.last_error = "Vigil sent an answer Jackil could not read."
        else:
            blob = str(answer.get("blob") or "")
            instance = str(answer.get("instance") or "")[:64]
            record.blob = blob
            record.vigil_instance = instance
            record.last_error = ""
            # Only a licence that verifies *and* is bound to this Vigil resets
            # the allowance for a Vigil Jackil can no longer reach.
            if blob and _verifies(blob, instance):
                record.last_verified_at = timezone.now()
    record.last_checked_at = timezone.now()
    record.save()


def _verifies(blob: str, instance: str) -> bool:
    try:
        claims = verify_blob(blob, settings.JACKIL_LICENSE_PUBLIC_KEY)
    except LicenceError:
        return False
    return bool(claims.instance) and claims.instance == instance


def _classify(record: LicenceRecord) -> Edition:
    """The licence in the stored record, judged as policy."""
    if not record.blob:
        detail = record.last_error or "No SQSY Business licence on the linked Vigil."
        return Edition("none", detail=detail)

    try:
        claims = verify_blob(record.blob, settings.JACKIL_LICENSE_PUBLIC_KEY)
    except LicenceError as exc:
        return Edition("invalid", detail=str(exc))

    if record.vigil_instance and claims.instance != record.vigil_instance:
        return Edition(
            "mismatch", claims=claims, detail="This licence was issued for a different Vigil."
        )
    if "jackil" not in claims.features:
        return Edition("not_included", claims=claims, detail="The licence does not include Jackil.")

    now = timezone.now()
    if record.last_verified_at is None or (now - record.last_verified_at).days >= GRACE_DAYS:
        return Edition(
            "unlinked",
            claims=claims,
            detail=f"Jackil has not reached Vigil for {GRACE_DAYS} days.",
        )

    expiry = claims.expiry_date
    if expiry is not None:
        grace_end = expiry + timedelta(days=GRACE_DAYS)
        if now > grace_end:
            return Edition(
                "lapsed", claims=claims, detail=f"This licence expired on {expiry:%d %b %Y}."
            )
        if now > expiry:
            days = (now - expiry).days + 1
            return Edition(
                "grace",
                claims=claims,
                detail=(
                    f"Expired {days} day{'' if days == 1 else 's'} ago; "
                    f"Business stays on until {grace_end:%d %b %Y}."
                ),
            )
    return Edition("valid", claims=claims, detail="This licence is valid.")

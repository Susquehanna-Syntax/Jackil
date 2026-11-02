"""Civil settings read by the mfa app, with defaults.

``apps/mfa`` is copied into Mercantil and Jackil, so everything app-specific
arrives here rather than through an import of a Civil module.
"""

from importlib import import_module

from django.conf import settings


def _dotted(path):
    module_path, _, name = path.rpartition(".")
    return getattr(import_module(module_path), name)


def issuer() -> str:
    return getattr(settings, "MFA_ISSUER", "Civil")


def public_url() -> str:
    """Where this install is opened from — the only origin a key may be bound
    to. Empty means security keys are unavailable here (see ``keys``)."""
    return getattr(settings, "MFA_PUBLIC_URL", "")


def rp_name() -> str:
    """The name an authenticator shows next to the account it belongs to."""
    return getattr(settings, "MFA_RP_NAME", "") or issuer()


def login_url() -> str:
    """The password sign-in page: the host app's own ``LOGIN_URL``."""
    from django.shortcuts import resolve_url

    return resolve_url(settings.LOGIN_URL)


def login_template() -> str:
    """The template the password step renders (the host app's sign-in page)."""
    return getattr(settings, "MFA_LOGIN_TEMPLATE", "login.html")


def required_fn():
    path = getattr(settings, "MFA_REQUIRED", f"{__package__}.policy.everyone")
    if callable(path):
        return path
    return _dotted(path)


def required(user) -> bool:
    return bool(required_fn()(user))


def trusted_backends() -> tuple[str, ...]:
    return tuple(getattr(settings, "MFA_TRUSTED_BACKENDS", ()))

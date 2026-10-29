"""Open-core feature registry.

Maps optional "pro" feature slugs to their Django app names and reports which
are installed, so the open core degrades gracefully when a pro app is absent.
The check is import-free: it only consults the app registry, never imports the
pro app.

The SQSY Business slugs are not apps at all — they follow the edition, worked
out from the licence on the linked Vigil (``apps.licensing.service``). The set
is duplicated here so this module stays importable at URL-import time without
pulling in the licensing app; a test keeps the two copies equal.
"""

from django.apps import apps as django_apps

# feature slug -> app config name
FEATURE_APPS = {
    "sla": "apps.sla",
    "automation": "apps.automation",
    "api": "apps.api",
    "reports": "apps.reports",
    "customfields": "apps.customfields",
}

# Duplicated from apps.licensing.service.BUSINESS_FEATURES on purpose; keep equal.
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


def feature_enabled(slug):
    """True when ``slug`` is on: Business slugs follow the licence, app slugs the registry."""
    if slug in BUSINESS_FEATURES:
        from apps.licensing import service

        return service.has_feature(slug)
    return django_apps.is_installed(FEATURE_APPS.get(slug, slug))


def enabled_features():
    """The set of enabled feature slugs."""
    return {slug for slug in FEATURE_APPS if feature_enabled(slug)}

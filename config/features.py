"""Open-core feature registry.

Maps optional "pro" feature slugs to their Django app names and reports which
are installed, so the open core degrades gracefully when a pro app is absent.
The check is import-free: it only consults the app registry, never imports the
pro app.
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


def feature_enabled(slug):
    """True if the pro app backing ``slug`` is installed."""
    return django_apps.is_installed(FEATURE_APPS.get(slug, slug))


def enabled_features():
    """The set of enabled feature slugs."""
    return {slug for slug in FEATURE_APPS if feature_enabled(slug)}

"""Portal feature gates and form choices."""

from config.features import feature_enabled


def styling_enabled() -> bool:
    return feature_enabled("portal_branding")


def can_add_portal() -> bool:
    from .models import Portal

    return styling_enabled() or not Portal.objects.exists()


def form_choices():
    """The active RequestForms as ``[(slug, name)]``; [] without the
    customfields app."""
    if not feature_enabled("customfields"):
        return []
    from apps.customfields.service import active_forms

    return [(form.slug, form.name) for form in list(active_forms())]

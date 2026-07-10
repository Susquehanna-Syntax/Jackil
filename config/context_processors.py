from .features import enabled_features


def features(request):
    """Expose the set of enabled pro-feature slugs to every template."""
    return {"enabled_features": enabled_features()}

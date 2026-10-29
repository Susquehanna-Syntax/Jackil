from .features import BUSINESS_FEATURES, enabled_features, feature_enabled


def features(request):
    """Expose the set of enabled optional-app slugs to every template."""
    return {"enabled_features": enabled_features()}


def business(request):
    """The SQSY Business slugs switched on by the licence; empty on any error."""
    try:
        return {"business_features": {s for s in BUSINESS_FEATURES if feature_enabled(s)}}
    except Exception:
        return {"business_features": set()}

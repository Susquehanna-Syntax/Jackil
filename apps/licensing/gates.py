"""The page a free Jackil shows when asked for an SQSY Business feature."""

from django.shortcuts import render

from config.features import feature_enabled


def business_page(request, slug: str, *, what: str):
    """The "part of SQSY Business" page, status 402, or None when the feature is on.

    Callers render its return value directly: ``None`` means carry on, a
    response means stop and show why the feature is not here.
    """
    if feature_enabled(slug):
        return None
    return render(
        request,
        "licensing/business_only.html",
        {
            "what": what,
            "slug": slug,
            "is_admin": getattr(request.user, "role", "") == "admin",
        },
        status=402,
    )

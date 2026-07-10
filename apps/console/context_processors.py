from .models import SiteBranding


def branding(request):
    try:
        return {"branding": SiteBranding.get()}
    except Exception:
        return {"branding": None}

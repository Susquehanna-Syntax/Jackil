"""``/admin/login/`` goes through Civil's two-step sign-in.

The Django admin has its own password form; leaving it reachable would hand
back exactly the bypass this phase removes everywhere else. Staff who are
already signed in reach the admin's index as before, so nothing about the
working path changes.
"""

from urllib.parse import urlencode

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect

from . import conf


def admin_login_redirect(request):
    """Anonymous or plain-password sessions start at ``/login/`` with the
    admin target kept as ``next``; a signed-in staff user goes straight in."""
    if request.user.is_authenticated and request.user.is_active and request.user.is_staff:
        return _admin_index(request)
    target = request.GET.get("next") or "/admin/"
    return redirect(f"{conf.login_url()}?{urlencode({'next': target})}")


@staff_member_required
def _admin_index(request):
    """The admin index, for someone who has already proved both factors.

    ``user_passes_test`` sends anyone who fails its test to ``settings.LOGIN_URL``
    with ``next`` — which is Civil's two-step sign-in, so there is no path
    through this view that skips the second factor.
    """
    from django.contrib import admin

    return admin.site.index(request)

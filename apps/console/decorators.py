from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def admin_required(view):
    """Allow only authenticated admins; others are redirected with a message."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("accounts:login")
        if request.user.role != "admin":
            messages.error(request, "You need administrator access for that.")
            return redirect("tickets:dashboard")
        return view(request, *args, **kwargs)

    return wrapper

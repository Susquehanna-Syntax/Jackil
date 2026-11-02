from rest_framework.permissions import BasePermission


class IsStaffRole(BasePermission):
    """Dashboards are for agents and admins. Customers get 403."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role in ("agent", "admin"))

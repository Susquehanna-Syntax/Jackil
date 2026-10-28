"""Projects: who may see the tracker, and who may see what anything costs."""

from apps.accounts.models import User

from .models import CostSettings


def can_see_projects(user) -> bool:
    return getattr(user, "role", None) in ("agent", "admin")


def can_admin_projects(user) -> bool:
    return getattr(user, "role", None) == "admin"


def can_see_cost(user) -> bool:
    """Costs are off for agents until an admin says otherwise."""
    role = getattr(user, "role", None)
    if role == "admin":
        return True
    if role == "agent":
        return CostSettings.get_solo().show_cost_totals_to_agents
    return False


def can_see_rates(user) -> bool:
    """Wages and hours-per-point are admin-only, whatever the cost setting says."""
    return getattr(user, "role", None) == "admin"


def staff_users():
    """Everyone who may be a lead, an assignee or a filter choice."""
    return User.objects.filter(role__in=["agent", "admin"]).order_by("username")

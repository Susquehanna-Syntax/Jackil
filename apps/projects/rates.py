"""The rates page: a wage and sprint hours for every colleague, plus cost settings."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from . import cost, permissions
from .forms import CostSettingsForm, RateForm
from .models import CostSettings, PersonRate
from .views import display_name


@login_required
def rates_page(request):
    if not permissions.can_admin_projects(request.user):
        raise PermissionDenied
    users = list(permissions.staff_users())
    posted = request.POST if request.method == "POST" else None
    action = posted.get("action") if posted is not None else None
    if action == "rates":
        return _save_rates(request, users, posted)
    if action == "settings":
        return _save_settings(request, users, posted)
    return _render(
        request, users, _rows(users, None), CostSettingsForm(instance=CostSettings.get_solo())
    )


def _save_rates(request, users, posted):
    rows = _rows(users, posted)
    if not all(row["form"].is_valid() for row in rows):
        return _render(
            request,
            users,
            rows,
            CostSettingsForm(instance=CostSettings.get_solo()),
            status=200,
        )
    for row in rows:
        data = row["form"].cleaned_data
        _save_rate(row["user"], data["hourly_wage"], data["sprint_hours"])
    messages.success(request, "Rates saved.")
    return redirect("projects:rates")


def _save_settings(request, users, posted):
    solo = CostSettings.get_solo()
    form = CostSettingsForm(posted, instance=solo)
    if form.is_valid():
        form.save()
        messages.success(request, "Cost settings saved.")
        return redirect("projects:rates")
    return _render(request, users, _rows(users, None), form, status=200)


def _render(request, users, rows, settings_form, status=200):
    return render(
        request,
        "projects/rates.html",
        {
            "rows": rows,
            "settings_form": settings_form,
            "currency": CostSettings.get_solo().currency,
        },
        status=status,
    )


def _rows(users, posted):
    """One row per staff user, bound to the posted data or to their saved rate."""
    rates = {rate.user_id: rate for rate in PersonRate.objects.filter(user__in=users)}
    rows = []
    for user in users:
        rate = rates.get(user.pk)
        initial = {"hourly_wage": None, "sprint_hours": None}
        if rate is not None:
            initial = {"hourly_wage": rate.hourly_wage, "sprint_hours": rate.sprint_hours}
        velocity = cost.velocity(user)
        rows.append(
            {
                "user": user,
                "name": display_name(user),
                "form": RateForm(posted, prefix=f"u{user.pk}", initial=initial),
                "hours_per_point": cost.hours_per_point(user),
                # cost.hours_per_point already falls back when velocity is
                # missing or zero, or sprint_hours is unset.
                "is_default": velocity is None or velocity == 0,
            }
        )
    return rows


def _save_rate(user, wage, hours) -> None:
    if wage is None and hours is None:
        PersonRate.objects.filter(user=user).delete()
        return
    PersonRate.objects.update_or_create(
        user=user, defaults={"hourly_wage": wage, "sprint_hours": hours}
    )

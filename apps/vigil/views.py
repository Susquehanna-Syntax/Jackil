from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.console.decorators import admin_required

from .client import VigilUnavailable, get_client, vigil_capabilities
from .forms import VigilConnectionForm
from .models import VigilConnection


@admin_required
def vigil_settings(request):
    connection = VigilConnection.get_solo()

    if request.method == "POST":
        if request.POST.get("action") == "test":
            _test(connection, request)
        else:
            _save(connection, request)
        return redirect("console:vigil_settings")

    form = VigilConnectionForm(
        initial={
            "base_url": connection.base_url,
            "enabled": connection.enabled,
        },
        has_key=bool(connection.key_encrypted),
    )
    return render(
        request,
        "vigil/settings.html",
        {
            "form": form,
            "connection": connection,
            "has_key": bool(connection.key_encrypted),
            "older_vigil": connection.is_configured and "devices" not in vigil_capabilities(),
            "section": "vigil",
        },
    )


def _save(connection, request):
    form = VigilConnectionForm(request.POST, has_key=bool(connection.key_encrypted))
    if not form.is_valid():
        for error in sorted(text for field_errors in form.errors.values() for text in field_errors):
            messages.error(request, error)
        return

    connection.base_url = (form.cleaned_data.get("base_url") or "").rstrip("/")
    connection.enabled = bool(form.cleaned_data.get("enabled"))
    key = form.cleaned_data.get("key") or ""
    if key:
        connection.set_key(key)
    connection.save()
    messages.success(request, "Vigil connection saved.")


def _test(connection, request):
    client = get_client()
    if client is None:
        messages.error(request, "Save the address and a key first.")
        return

    ok = False
    note = ""
    try:
        answer = client.ping()
        version = str(answer.get("version") or "")
        acting_as = str(answer.get("acting_as") or "")
        note = f"Connected to Vigil {version} as {acting_as}."
        connection.vigil_version = version[:40]
        ok = True
    except VigilUnavailable as failure:
        note = str(failure)

    connection.last_checked_at = timezone.now()
    connection.last_ok = ok
    connection.last_message = note[:300]
    connection.save(update_fields=["last_checked_at", "last_ok", "last_message", "vigil_version"])

    if ok:
        messages.success(request, note)
    else:
        messages.error(request, note)

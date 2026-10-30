from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.console.decorators import admin_required

from .client import VigilUnavailable, get_client, vigil_capabilities
from .devices import can_write_devices
from .forms import VigilConnectionForm
from .models import VigilConnection
from .move import KEY_CANNOT_WRITE, SuggestionUnavailable, movable_items, move_all, suggest_match


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
            "movable": _movable(),
            "section": "vigil",
        },
    )


def _movable() -> dict:
    """Every device-like item Jackil still holds, with the Vigil thing it matches.

    ``can_write`` is whether this key may move them at all; without it the
    card says what to tick in Vigil instead of offering a button. A Vigil that
    cannot be asked what an item matches is named on that item's row.
    """
    can_write = can_write_devices()
    client = get_client() if can_write else None
    rows = []
    for item in movable_items():
        match, error = {}, ""
        if client is not None:
            try:
                match = suggest_match(client, item) or {}
            except SuggestionUnavailable as failure:
                error = str(failure)
        rows.append({"name": item.name, "match": match, "error": error})
    return {
        "can_write": can_write,
        "reason": "" if can_write else KEY_CANNOT_WRITE,
        "items": rows,
    }


@admin_required
def vigil_move_devices(request):
    """Move every device-like Dynamic Item into Vigil, and say what happened."""
    if request.method != "POST":
        return redirect("console:vigil_settings")

    results = move_all(request.user)
    moved = sum(1 for _, status, _ in results if status == "moved")
    failed = [name for name, status, _ in results if status == "failed"]
    if moved:
        messages.success(request, f"Moved {moved} device{'' if moved == 1 else 's'} into Vigil.")
    if failed:
        messages.error(
            request, f"{len(failed)} could not be moved: {', '.join(failed)}. Try again."
        )
    if not results:
        messages.info(request, "There was nothing to move.")

    client = get_client()
    return render(
        request,
        "vigil/move_results.html",
        {
            "results": [
                {
                    "name": name,
                    "status": status,
                    "detail": detail,
                    "device": status == "moved" and detail.startswith("vigil:device:"),
                    "host": status == "moved" and detail.startswith("vigil:host:"),
                    "open_url": _open_url(client, detail) if status == "moved" else "",
                }
                for name, status, detail in results
            ],
            "moved": moved,
            "failed": len(failed),
            "section": "vigil",
        },
    )


def _open_url(client, target: str) -> str:
    """The Vigil page for a device we just created there; a host was already there."""
    if client is None or not target.startswith("vigil:device:"):
        return ""
    return f"{client.base_url.rstrip('/')}/#open/device/{target.split(':', 2)[2]}"


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

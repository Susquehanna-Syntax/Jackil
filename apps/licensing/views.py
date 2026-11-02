from django.contrib import messages
from django.shortcuts import redirect, render

from apps.console.decorators import admin_required

from . import service
from .models import LicenceRecord


@admin_required
def edition_settings(request):
    if request.method == "POST":
        edition = service.refresh()
        messages.success(request, f"Checked the licence: {edition.detail}")
        return redirect("console:edition_settings")

    edition = service.current()
    record = LicenceRecord.objects.filter(pk=1).first() or LicenceRecord(pk=1)
    return render(
        request,
        "licensing/edition.html",
        {
            "edition": edition,
            "business": edition.business,
            "claims": edition.claims,
            "record": record,
            "section": "edition",
        },
    )

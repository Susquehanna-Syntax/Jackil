"""The two reports pages: the list of reports you can see, and one report."""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.reports.api import DEFAULT_CARDS
from apps.reports.compute import visible_reports
from apps.reports.models import Report
from apps.reports.widgets import REPORT_WIDGETS

STAFF_ROLES = ("agent", "admin")


@login_required
def reports_home(request):
    """The Reports page: every report the caller owns or that is shared."""
    if request.user.role not in STAFF_ROLES:
        return redirect("tickets:dashboard")
    ctx = {"reports": list(visible_reports(request.user))}
    return render(request, "reports/list.html", ctx)


@login_required
def report_create(request):
    """The New report button: a default card set, straight to its page."""
    if request.user.role not in STAFF_ROLES:
        return redirect("tickets:dashboard")
    report = Report.objects.create(
        name="Untitled report", owner=request.user, widgets=DEFAULT_CARDS
    )
    return redirect("reports:report_page", report_id=report.pk)


@login_required
def report_page(request, report_id):
    """One report: a twelve-column grid with one card box per saved card."""
    if request.user.role not in STAFF_ROLES:
        return redirect("tickets:dashboard")
    report = visible_reports(request.user).filter(id=report_id).first()
    if report is None:
        raise Http404("No such report.")

    cards = _cards(report)
    return render(request, "reports/report.html", {"report": report, "cards": cards})


def _cards(report):
    """The saved cards that still name a known kind, each with its CSV link.

    The index is the card's position in ``report.widgets``, so a retired kind
    leaves a hole rather than shifting every later card onto the wrong data.
    """
    cards = []
    for position, card in enumerate(report.widgets):
        entry = REPORT_WIDGETS.get(card.get("kind"))
        if entry is None:
            continue
        size = entry["size"]
        cards.append(
            {
                "index": position,
                "title": card.get("title") or entry["title"],
                "how": entry["how"],
                "w": _grid(card, "w", size["w"]),
                "h": _grid(card, "h", size["h"]),
                "csv_url": reverse("reports:report_data_csv", args=[report.pk, position]),
            }
        )
    return cards


def _grid(card, key, fallback):
    value = card.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value

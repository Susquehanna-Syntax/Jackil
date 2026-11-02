"""Filtering the ticket list, shared by the ticket-list view and widgets.

Lives apart from ``views`` because phase-02's widgets apply a saved view's
encoded querystring to a queryset without going through an HTTP request.
"""

from django.db.models import Q


def filter_tickets(qs, params, user):
    """Apply the ticket list's query-string filters to *qs*.

    ``params`` is any mapping with ``.get`` — a ``QueryDict`` from a real
    request, or one built from a saved view's stored querystring.
    """
    status = params.get("status")
    priority = params.get("priority")
    assigned = params.get("assigned")
    search = (params.get("search") or "").strip()

    if status:
        qs = qs.filter(status=status)
    if priority:
        qs = qs.filter(priority=priority)
    if assigned == "mine":
        qs = qs.filter(assigned_to=user)
    elif assigned == "unassigned":
        qs = qs.filter(assigned_to__isnull=True)
    if search:
        qs = qs.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(tags__icontains=search)
        )
    return qs

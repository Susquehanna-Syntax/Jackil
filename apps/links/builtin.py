import re
from dataclasses import replace

from django.urls import reverse
from django.utils import timezone

from .registry import LinkTarget, Resolver, register_type

#: A path ending /tickets/<digits>/, with or without a scheme and host.
_TICKET_URL = re.compile(r"(?:^|/)tickets/(\d+)/$")

VIGIL_KINDS = ("host", "task", "playbook", "run", "automation")


def person_name(user) -> str:
    """How we name a person everywhere: full name, falling back to username."""
    if user is None:
        return ""
    return user.get_full_name() or user.username


def _months(value) -> str:
    return timezone.localdate(value).strftime("%d %b %Y")


class TicketResolver(Resolver):
    def resolve(self, ids: list[str], user) -> dict[str, LinkTarget]:
        from apps.tickets.models import Ticket

        numeric = [int(i) for i in ids if i.isdigit()]
        targets = {}
        for ticket in Ticket.objects.filter(pk__in=numeric):
            if _visible(ticket, user):
                targets[str(ticket.pk)] = _target(ticket)
        return targets

    def search(self, q: str, user, limit: int) -> list[LinkTarget]:
        from apps.tickets.models import Ticket

        term = q.strip()
        if not term:
            return []
        ordered = list(Ticket.objects.filter(title__icontains=term).order_by("-created_at"))
        digits = term[1:] if term.startswith("#") else term
        if digits.isdigit():
            exact = Ticket.objects.filter(pk=int(digits)).first()
            # The number the user typed is a better answer than a title that
            # happens to contain the same digits.
            if exact is not None:
                ordered = [exact] + [t for t in ordered if t.pk != exact.pk]
        return [_target(t) for t in ordered if _visible(t, user)][:limit]

    def recent(self, user, limit: int) -> list[LinkTarget]:
        from apps.tickets.models import Ticket

        tickets = [t for t in Ticket.objects.order_by("-updated_at") if _visible(t, user)]
        return [_target(t) for t in tickets[:limit]]

    def preview(self, id: str, user) -> LinkTarget | None:
        from apps.tickets.models import Ticket

        ticket = Ticket.objects.filter(pk=id).first() if id.isdigit() else None
        if ticket is None or not _visible(ticket, user):
            return None
        return replace(
            _target(ticket),
            facts=(
                ("Status", ticket.get_status_display()),
                ("Priority", ticket.get_priority_display()),
                ("Assignee", person_name(ticket.assigned_to) or "Unassigned"),
                ("Opened", _months(ticket.created_at) if ticket.created_at else ""),
            ),
        )

    def from_url(self, url: str) -> str | None:
        match = _TICKET_URL.search(url)
        return match.group(1) if match else None


def _visible(ticket, user) -> bool:
    from apps.tickets.permissions import can_view_ticket

    return can_view_ticket(user, ticket)


def _target(ticket) -> LinkTarget:
    return LinkTarget(
        type="ticket",
        id=str(ticket.pk),
        label=f"#{ticket.pk} {ticket.title}",
        url=reverse("tickets:ticket_detail", args=[ticket.pk]),
        status=ticket.get_status_display(),
        tone="ok" if ticket.status in ("resolved", "closed") else "info",
    )


class VigilStubResolver(Resolver):
    """Placeholder for the vigil-owned types until M6 registers real resolvers."""

    def __init__(self, kind: str):
        self.kind = kind

    def resolve(self, ids: list[str], user) -> dict[str, LinkTarget]:
        return {
            i: LinkTarget(
                type=self.kind,
                id=i,
                label=i,
                status="Vigil not connected",
                tone="muted",
                available=False,
            )
            for i in ids
        }

    def search(self, q: str, user, limit: int) -> list[LinkTarget]:
        return []


def register_builtin_types() -> None:
    register_type("ticket", TicketResolver())
    for kind in VIGIL_KINDS:
        register_type(f"vigil:{kind}", VigilStubResolver(f"vigil:{kind}"))

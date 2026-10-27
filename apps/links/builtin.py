import re

from django.urls import reverse

from .registry import LinkTarget, Resolver, register_type

#: A path ending /tickets/<digits>/, with or without a scheme and host.
_TICKET_URL = re.compile(r"(?:^|/)tickets/(\d+)/$")

VIGIL_KINDS = ("host", "task", "playbook", "run", "automation")


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

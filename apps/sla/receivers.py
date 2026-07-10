from django.dispatch import receiver

from apps.tickets.events import ticket_created, ticket_replied


@receiver(ticket_created)
def on_ticket_created(sender, ticket, **kwargs):
    from .service import apply_sla

    apply_sla(ticket)


@receiver(ticket_replied)
def on_ticket_replied(sender, ticket, author, kind, **kwargs):
    if (
        kind == "reply"
        and author is not None
        and getattr(author, "role", "")
        in (
            "agent",
            "admin",
        )
    ):
        from .service import mark_first_response

        mark_first_response(ticket)

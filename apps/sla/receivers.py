from django.dispatch import receiver

from apps.tickets.events import (
    ticket_created,
    ticket_priority_changed,
    ticket_replied,
    ticket_status_changed,
)


@receiver(ticket_created)
def on_ticket_created(sender, ticket, **kwargs):
    from .service import apply_sla

    apply_sla(ticket)


@receiver(ticket_status_changed)
def on_ticket_status_changed(sender, ticket, actor, new_status, **kwargs):
    """Pause the SLA clock while the ticket sits in a paused status (Pending),
    and resume it — shifting due dates by the paused span — when it leaves."""
    from .service import PAUSED_STATUSES, pause_sla, resume_sla

    if new_status in PAUSED_STATUSES:
        pause_sla(ticket)
    else:
        resume_sla(ticket)


@receiver(ticket_priority_changed)
def on_ticket_priority_changed(sender, ticket, actor, old_priority, new_priority, **kwargs):
    """Recompute the due dates against the new priority's SLA target."""
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

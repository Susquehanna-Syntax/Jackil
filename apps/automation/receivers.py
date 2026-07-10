from django.dispatch import receiver

from apps.tickets.events import ticket_created, ticket_replied, ticket_status_changed


@receiver(ticket_created)
def on_ticket_created(sender, ticket, **kwargs):
    from .engine import run_rules

    run_rules(ticket, "on_create")


@receiver(ticket_replied)
def on_ticket_replied(sender, ticket, author, **kwargs):
    from .engine import run_rules

    run_rules(ticket, "on_reply", actor=author)


@receiver(ticket_status_changed)
def on_ticket_status_changed(sender, ticket, actor, **kwargs):
    from .engine import run_rules

    run_rules(ticket, "on_status_change", actor=actor)

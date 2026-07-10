from django.dispatch import receiver

from apps.tickets.events import ticket_created, ticket_status_changed


@receiver(ticket_created)
def on_ticket_created(sender, ticket, **kwargs):
    from .webhooks import fire_webhooks

    fire_webhooks("ticket.created", ticket)


@receiver(ticket_status_changed)
def on_ticket_status_changed(sender, ticket, **kwargs):
    from .webhooks import fire_webhooks

    fire_webhooks("ticket.updated", ticket)

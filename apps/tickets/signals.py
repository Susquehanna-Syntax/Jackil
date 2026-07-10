from django.db.models.signals import post_save
from django.dispatch import receiver

from .events import ticket_created
from .models import Ticket


@receiver(post_save, sender=Ticket)
def emit_ticket_created(sender, instance, created, **kwargs):
    if not created:
        return
    ticket_created.send(sender=Ticket, ticket=instance)

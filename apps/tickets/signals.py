from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Ticket


@receiver(post_save, sender=Ticket)
def apply_sla_on_create(sender, instance, created, **kwargs):
    if not created:
        return
    from apps.sla.service import apply_sla

    apply_sla(instance)  # saves first_response_due / resolution_due

    from apps.automation.engine import run_rules

    run_rules(instance, "on_create")

    from apps.api.webhooks import fire_webhooks

    fire_webhooks("ticket.created", instance)

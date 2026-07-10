from .models import Notification


def notify(recipient, verb, actor=None, ticket=None):
    """Create a notification, skipping self-notifications and missing recipients."""
    if recipient is None:
        return None
    if actor is not None and actor.pk == recipient.pk:
        return None
    return Notification.objects.create(recipient=recipient, actor=actor, verb=verb, ticket=ticket)


def notify_ticket_participants(ticket, verb, actor=None, exclude=None):
    """Notify the requester and assignees of a ticket (minus actor/exclude)."""
    seen = set()
    exclude_ids = {u.pk for u in (exclude or []) if u}
    recipients = []
    if ticket.created_by_id:
        recipients.append(ticket.created_by)
    if ticket.assigned_to_id:
        recipients.append(ticket.assigned_to)
    recipients.extend(ticket.assigned_users.all())
    for r in recipients:
        if r.pk in seen or r.pk in exclude_ids:
            continue
        seen.add(r.pk)
        notify(r, verb, actor=actor, ticket=ticket)

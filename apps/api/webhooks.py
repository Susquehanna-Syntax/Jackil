"""Outbound webhooks — fire a JSON POST to subscribers on ticket events.

Uses urllib (stdlib) so there is no extra dependency. Delivery is best-effort and
synchronous; failures are recorded on the webhook, never raised into the caller.
"""

import json
import urllib.error
import urllib.request

from django.utils import timezone


def _payload(event, ticket):
    return {
        "event": event,
        "ticket": {
            "id": ticket.id,
            "title": ticket.title,
            "status": ticket.status,
            "priority": ticket.priority,
            "source": ticket.source,
            "requester_email": ticket.requester_email
            or (ticket.created_by.email if ticket.created_by_id else ""),
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        },
    }


def fire_webhooks(event, ticket):
    """Deliver ``event`` for ``ticket`` to all active matching webhooks."""
    from .models import Webhook

    try:
        hooks = list(Webhook.objects.filter(is_active=True, event=event))
    except Exception:
        return 0
    if not hooks:
        return 0
    body = json.dumps(_payload(event, ticket)).encode()
    delivered = 0
    for hook in hooks:
        status = "ok"
        try:
            req = urllib.request.Request(
                hook.url,
                data=body,
                headers={"Content-Type": "application/json", "X-Jackil-Event": event},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = f"{resp.status}"
                delivered += 1
        except urllib.error.HTTPError as exc:
            status = f"http {exc.code}"
        except Exception as exc:  # noqa: BLE001
            status = f"error: {exc}"[:60]
        Webhook.objects.filter(pk=hook.pk).update(last_fired_at=timezone.now(), last_status=status)
    return delivered

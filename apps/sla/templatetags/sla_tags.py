from django import template
from django.utils import timezone

from apps.sla.service import resolution_status, response_status

register = template.Library()

_SEVERITY = {"breached": 4, "overdue": 3, "open": 1, "met": 0, "none": -1}


@register.inclusion_tag("sla/_badge.html")
def sla_badge(ticket, kind, compact=False):
    """Render an SLA status pill for the response or resolution target."""
    now = timezone.now()
    if kind == "response":
        status = response_status(ticket, now)
        due = ticket.first_response_due
        label = "First response"
    else:
        status = resolution_status(ticket, now)
        due = ticket.resolution_due
        label = "Resolution"
    return {"status": status, "due": due, "label": label, "compact": compact}


@register.simple_tag
def sla_worst(ticket):
    """The more urgent of the two SLA statuses (for compact list indicators)."""
    now = timezone.now()
    r = response_status(ticket, now)
    res = resolution_status(ticket, now)
    return r if _SEVERITY.get(r, 0) >= _SEVERITY.get(res, 0) else res

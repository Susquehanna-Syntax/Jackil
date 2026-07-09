"""Automation rule engine — evaluate conditions and apply actions on tickets.

Kept dependency-light and defensive: malformed rules never raise into the ticket
lifecycle, they just don't match / don't apply.
"""

from django.utils import timezone

# Fields a condition may read off a ticket.
CONDITION_FIELDS = ["priority", "status", "source", "title", "description", "tags", "department"]

# Action types a rule may apply.
ACTION_TYPES = ["set_priority", "set_status", "add_tag", "assign", "add_note"]


def _get_field(ticket, field):
    if field == "department":
        return ticket.department.name if ticket.department_id else ""
    return getattr(ticket, field, "")


def _check_condition(ticket, cond):
    try:
        field = cond["field"]
        op = cond.get("op", "eq")
        value = cond.get("value", "")
    except (TypeError, KeyError):
        return False
    actual = str(_get_field(ticket, field) or "")
    value = str(value or "")
    if op == "eq":
        return actual.lower() == value.lower()
    if op == "ne":
        return actual.lower() != value.lower()
    if op == "contains":
        return value.lower() in actual.lower()
    return False


def rule_matches(rule, ticket):
    """All conditions must pass (an empty condition list always matches)."""
    conds = rule.conditions if isinstance(rule.conditions, list) else []
    return all(_check_condition(ticket, c) for c in conds)


def apply_actions(rule, ticket, actor=None):
    """Apply a rule's actions to a ticket. Returns the list of applied action
    types. Saves the ticket and records system events for visible changes."""
    from apps.tickets.services import record_system_event

    actions = rule.actions if isinstance(rule.actions, list) else []
    applied = []
    changed_fields = []
    for act in actions:
        if not isinstance(act, dict):
            continue
        atype = act.get("type")
        value = act.get("value", "")
        if atype == "set_priority" and value in ("critical", "high", "medium", "low"):
            ticket.priority = value
            changed_fields.append("priority")
            applied.append(atype)
        elif atype == "set_status" and value in (
            "open",
            "in_progress",
            "pending",
            "resolved",
            "closed",
        ):
            ticket.status = value
            changed_fields.append("status")
            applied.append(atype)
        elif atype == "add_tag" and value:
            tags = [t.strip() for t in (ticket.tags or "").split(",") if t.strip()]
            if value not in tags:
                tags.append(value)
                ticket.tags = ", ".join(tags)
                changed_fields.append("tags")
            applied.append(atype)
        elif atype == "assign" and value:
            from apps.accounts.models import User

            agent = User.objects.filter(pk=value, role__in=["agent", "admin"]).first()
            if agent:
                ticket.assigned_to = agent
                changed_fields.append("assigned_to")
                applied.append(atype)
        elif atype == "add_note" and value:
            record_system_event(ticket, actor, f"Automation note: {value}")
            applied.append(atype)
    if changed_fields:
        ticket.save(update_fields=list(set(changed_fields)))
    return applied


def run_rules(ticket, event, actor=None):
    """Run all active rules for ``event`` against ``ticket``. Returns the count
    of rules that matched and applied. Never raises."""
    from .models import AutomationRule

    matched = 0
    try:
        rules = AutomationRule.objects.filter(is_active=True, trigger=event)
    except Exception:
        return 0
    for rule in rules:
        try:
            if rule_matches(rule, ticket):
                applied = apply_actions(rule, ticket, actor=actor)
                if applied:
                    matched += 1
                    AutomationRule.objects.filter(pk=rule.pk).update(
                        last_run_at=timezone.now(), run_count=rule.run_count + 1
                    )
        except Exception:
            continue
    return matched

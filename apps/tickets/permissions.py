def can_view_ticket(user, ticket):
    """Customers see only their own tickets; agents/admins see all."""
    if user.role in ("admin", "agent"):
        return True
    return ticket.created_by_id == user.id


def can_edit_ticket(user, ticket):
    if user.role in ("admin", "agent"):
        return True
    return user.role == "customer" and ticket.created_by_id == user.id


def can_manage_ticket(user):
    return user.role in ("admin", "agent")


def can_assign_ticket(user):
    return user.role in ("admin", "agent")


def can_post_internal(user):
    """Only agents/admins may post internal notes."""
    return user.role in ("admin", "agent")


def is_admin(user):
    return user.role == "admin"


def visible_messages(user, ticket):
    """Return the ticket's messages this user may see, oldest first.

    Customers see only public messages (public replies + outgoing/incoming
    email that is public); agents and admins see everything including notes
    and system events.
    """
    qs = ticket.messages.select_related("author").order_by("created_at")
    if user.role == "customer":
        qs = qs.filter(is_public=True)
    return qs

from django.dispatch import Signal

# Emitted after a ticket is first created. kwargs: ticket
ticket_created = Signal()

# Emitted after a public reply/incoming email is posted.
# kwargs: ticket, author, message, kind
ticket_replied = Signal()

# Emitted after a ticket's status changes.
# kwargs: ticket, actor, new_status
ticket_status_changed = Signal()

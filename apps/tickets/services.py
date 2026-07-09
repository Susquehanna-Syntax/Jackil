"""Domain services for tickets — message posting, attachments, system events.

Kept out of views so they are reusable from the web UI, the API, and email
ingestion, and are unit-testable in isolation.
"""

from django.conf import settings

from .models import Attachment, TicketMessage


class AttachmentTooLarge(Exception):
    """Raised when an uploaded file exceeds MAX_ATTACHMENT_SIZE."""

    def __init__(self, name, size):
        self.name = name
        self.size = size
        super().__init__(f"{name} is too large ({size} bytes)")


def add_attachments(ticket, message, files, uploaded_by=None):
    """Attach uploaded files to a ticket/message. ``files`` is a list of
    Django UploadedFile objects. Raises AttachmentTooLarge on oversize files."""
    max_size = getattr(settings, "MAX_ATTACHMENT_SIZE", 25 * 1024 * 1024)
    created = []
    for f in files:
        if not f:
            continue
        if f.size and f.size > max_size:
            raise AttachmentTooLarge(f.name, f.size)
        created.append(
            Attachment.objects.create(
                ticket=ticket,
                message=message,
                file=f,
                original_name=f.name[:255],
                content_type=getattr(f, "content_type", "") or "",
                size=f.size or 0,
                uploaded_by=uploaded_by,
            )
        )
    return created


def post_message(ticket, author, body, kind="reply", files=None, is_public=None):
    """Create a TicketMessage and attach any files.

    ``is_public`` defaults to True for replies/outgoing email and False for
    notes/system events. Returns the created message.
    """
    if is_public is None:
        is_public = kind in ("reply", "incoming_email", "outgoing_email")
    message = TicketMessage.objects.create(
        ticket=ticket,
        author=author,
        kind=kind,
        body=body or "",
        is_public=is_public,
    )
    if files:
        add_attachments(ticket, message, files, uploaded_by=author)
    return message


def record_system_event(ticket, actor, text):
    """Record an internal audit event on the ticket timeline (agents only)."""
    return TicketMessage.objects.create(
        ticket=ticket,
        author=actor,
        kind="system",
        body=text,
        is_public=False,
    )

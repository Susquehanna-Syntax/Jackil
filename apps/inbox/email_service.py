from django.core.mail import EmailMultiAlternatives

from .models import Inbox


def recipient_for(ticket):
    """Best email address to reach the ticket requester, or ''."""
    if ticket.requester_email:
        return ticket.requester_email
    if ticket.created_by and ticket.created_by.email:
        return ticket.created_by.email
    return ""


def send_ticket_reply(message):
    """Email a public reply to the ticket requester, threaded. Sets email
    metadata + email_status on the message. Returns True if an email was
    sent, False if skipped (no inbox / no recipient). Never raises for
    delivery errors — records email_status='failed' instead."""
    ticket = message.ticket
    inbox = Inbox.get_default()
    to_addr = recipient_for(ticket)
    if inbox is None or not to_addr:
        return False

    subject = f"[#{ticket.id}] {ticket.title}"
    # Thread onto the most recent inbound email if present.
    last_in = (
        ticket.messages.filter(kind="incoming_email")
        .exclude(message_id="")
        .order_by("-created_at")
        .first()
    )
    headers = {"Reply-To": inbox.reply_to_address(ticket.id)}
    if last_in and last_in.message_id:
        headers["In-Reply-To"] = last_in.message_id
        headers["References"] = last_in.message_id

    body = message.body
    if inbox.signature:
        body = f"{body}\n\n--\n{inbox.signature}"

    email = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=f"{inbox.name} <{inbox.email_address}>",
        to=[to_addr],
        headers=headers,
        connection=inbox.get_connection(),
    )
    message.from_email = inbox.email_address
    message.to_email = to_addr
    message.message_id = email.message().get("Message-ID", "")
    try:
        email.send()
        message.email_status = "sent"
    except Exception:
        message.email_status = "failed"
    message.save(update_fields=["from_email", "to_email", "message_id", "email_status"])
    return message.email_status == "sent"

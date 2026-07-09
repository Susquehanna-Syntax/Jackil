import re
from email import message_from_bytes
from email.policy import default as default_policy
from email.utils import parseaddr

from django.core.files.base import ContentFile
from django.utils import timezone

PLUS_TOKEN_RE = re.compile(r"\+(\d+)@")
SUBJECT_TOKEN_RE = re.compile(r"\[#(\d+)\]")


def parse_email(raw_bytes):
    msg = message_from_bytes(raw_bytes, policy=default_policy)
    from_name, from_addr = parseaddr(msg.get("From", ""))
    to_headers = " ".join(
        filter(None, [msg.get("To", ""), msg.get("Cc", ""), msg.get("Delivered-To", "")])
    )
    # Prefer the plain-text body; fall back to stripped HTML.
    body = ""
    try:
        part = msg.get_body(preferencelist=("plain",))
        if part is not None:
            body = part.get_content()
        else:
            html_part = msg.get_body(preferencelist=("html",))
            if html_part is not None:
                body = re.sub(r"<[^>]+>", "", html_part.get_content())
    except Exception:
        body = ""
    attachments = []
    for att in msg.iter_attachments():
        filename = att.get_filename()
        if not filename:
            continue
        payload = att.get_content()
        if isinstance(payload, str):
            payload = payload.encode("utf-8", "replace")
        attachments.append(
            {
                "filename": filename,
                "content_type": att.get_content_type(),
                "content": payload,
            }
        )
    return {
        "from_name": from_name,
        "from_addr": from_addr.lower(),
        "to_headers": to_headers,
        "subject": msg.get("Subject", "") or "",
        "message_id": (msg.get("Message-ID", "") or "").strip(),
        "in_reply_to": (msg.get("In-Reply-To", "") or "").strip(),
        "body": (body or "").strip(),
        "attachments": attachments,
    }


def find_ticket(parsed):
    # 1) plus-address token in To/Cc/Delivered-To
    m = PLUS_TOKEN_RE.search(parsed["to_headers"])
    # 2) [#id] token in the subject
    if not m:
        m = SUBJECT_TOKEN_RE.search(parsed["subject"])
    if m:
        from apps.tickets.models import Ticket

        return Ticket.objects.filter(pk=int(m.group(1))).first()
    return None


def get_or_create_requester(addr, display_name=""):
    from apps.accounts.models import User

    addr = (addr or "").lower()
    existing = User.objects.filter(email__iexact=addr).first()
    if existing:
        return existing
    base = re.sub(r"[^a-z0-9._-]", "", addr.split("@")[0]) or "user"
    username = base
    i = 1
    while User.objects.filter(username=username).exists():
        i += 1
        username = f"{base}{i}"
    first, _, last = display_name.partition(" ")
    user = User.objects.create_user(
        username=username,
        email=addr,
        role="customer",
        first_name=first[:150],
        last_name=last[:150],
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])
    return user


def ingest_email(raw_bytes, inbox=None):
    from apps.tickets.models import Attachment, Ticket, TicketMessage

    parsed = parse_email(raw_bytes)
    mid = parsed["message_id"]
    if mid and TicketMessage.objects.filter(message_id=mid).exists():
        return {"status": "duplicate", "ticket": None, "message": None}

    ticket = find_ticket(parsed)
    created_ticket = False
    requester = get_or_create_requester(parsed["from_addr"], parsed["from_name"])
    if ticket is None:
        subject = SUBJECT_TOKEN_RE.sub("", parsed["subject"]).strip() or "(no subject)"
        ticket = Ticket.objects.create(
            title=subject[:255],
            description=parsed["body"],
            created_by=requester,
            source="email",
            requester_email=parsed["from_addr"],
            status="open",
        )
        created_ticket = True

    message = TicketMessage.objects.create(
        ticket=ticket,
        author=requester if requester else None,
        kind="incoming_email",
        body=parsed["body"],
        is_public=True,
        from_email=parsed["from_addr"],
        message_id=mid,
        in_reply_to=parsed["in_reply_to"],
        created_at=timezone.now(),
    )
    for att in parsed["attachments"]:
        cf = ContentFile(att["content"], name=att["filename"])
        Attachment.objects.create(
            ticket=ticket,
            message=message,
            file=cf,
            original_name=att["filename"][:255],
            content_type=att["content_type"][:120],
            size=len(att["content"]),
            uploaded_by=requester,
        )
    # Reopen a resolved/closed ticket when the customer replies.
    if not created_ticket and ticket.status in ("resolved", "closed"):
        ticket.status = "open"
        ticket.closed_at = None
        ticket.save(update_fields=["status", "closed_at"])
    return {
        "status": "created" if created_ticket else "appended",
        "ticket": ticket,
        "message": message,
    }

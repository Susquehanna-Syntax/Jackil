import imaplib

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.inbox.ingest import ingest_email
from apps.inbox.models import Inbox


class Command(BaseCommand):
    help = "Fetch inbound email over IMAP and thread it onto tickets."

    def add_arguments(self, parser):
        parser.add_argument("--inbox", type=int, help="Only poll this inbox id.")

    def handle(self, *args, **options):
        inboxes = Inbox.objects.filter(active=True).exclude(imap_host="")
        if options.get("inbox"):
            inboxes = inboxes.filter(pk=options["inbox"])
        for inbox in inboxes:
            try:
                count = self._poll_one(inbox)
                inbox.last_poll_status = f"ok: {count} message(s)"
            except Exception as exc:  # noqa: BLE001
                inbox.last_poll_status = f"error: {exc}"[:255]
            inbox.last_polled_at = timezone.now()
            inbox.save(update_fields=["last_polled_at", "last_poll_status"])
            self.stdout.write(f"{inbox.email_address}: {inbox.last_poll_status}")

    def _poll_one(self, inbox):
        conn = (imaplib.IMAP4_SSL if inbox.imap_use_ssl else imaplib.IMAP4)(
            inbox.imap_host, inbox.imap_port
        )
        conn.login(inbox.imap_username or inbox.email_address, inbox.imap_password)
        conn.select(inbox.imap_folder)
        typ, data = conn.search(None, "UNSEEN")
        ids = data[0].split() if data and data[0] else []
        count = 0
        for num in ids:
            typ, msg_data = conn.fetch(num, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            ingest_email(raw, inbox=inbox)
            conn.store(num, "+FLAGS", "\\Seen")
            count += 1
        conn.logout()
        return count

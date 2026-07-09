from email.message import EmailMessage
from email.mime.base import MIMEBase
from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User
from apps.inbox.ingest import (
    find_ticket,
    get_or_create_requester,
    ingest_email,
    parse_email,
)
from apps.tickets.models import Ticket


def _raw(
    sender="a@ex.com",
    to="support@jackil.local",
    subject="Help",
    body="hi",
    mid="<m1@ex>",
    in_reply_to="",
    cc="",
):
    m = EmailMessage()
    m["From"] = sender
    m["To"] = to
    m["Subject"] = subject
    m["Message-ID"] = mid
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    if cc:
        m["Cc"] = cc
    m.set_content(body)
    return m.as_bytes()


def _raw_with_attachment(
    sender="a@ex.com", to="support@jackil.local", filename="file.txt", content=b"hello"
):
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    m = MIMEMultipart()
    m["From"] = sender
    m["To"] = to
    m["Subject"] = "With attachment"
    m["Message-ID"] = "<m-att@ex>"
    body = MIMEText("body text")
    m.attach(body)
    att = MIMEBase("text", "plain")
    att.set_payload(content)
    att.add_header("Content-Disposition", "attachment", filename=filename)
    m.attach(att)
    return m.as_bytes()


class TestParseEmail(TestCase):
    def test_parses_basic_fields(self):
        data = parse_email(_raw(sender="Sender <from@example.com>", to="to@example.com"))
        self.assertEqual(data["from_name"], "Sender")
        self.assertEqual(data["from_addr"], "from@example.com")
        self.assertIn("to@example.com", data["to_headers"])
        self.assertEqual(data["subject"], "Help")
        self.assertEqual(data["message_id"], "<m1@ex>")
        self.assertEqual(data["body"], "hi")

    def test_cc_included_in_to_headers(self):
        data = parse_email(_raw(cc="cc@example.com"))
        self.assertIn("cc@example.com", data["to_headers"])

    def test_strips_html_when_no_plain_part(self):
        from email.mime.text import MIMEText

        m = MIMEText("<p>Hello <b>world</b></p>", _subtype="html")
        m["From"] = "a@ex.com"
        m["To"] = "b@ex.com"
        m["Message-ID"] = "<html-1@ex>"
        data = parse_email(m.as_bytes())
        self.assertEqual(data["body"], "Hello world")

    def test_attachments_parsed(self):
        raw = _raw_with_attachment()
        data = parse_email(raw)
        self.assertEqual(len(data["attachments"]), 1)
        self.assertEqual(data["attachments"][0]["filename"], "file.txt")
        self.assertEqual(data["attachments"][0]["content"], b"hello")

    def test_no_attachments_for_empty(self):
        data = parse_email(_raw())
        self.assertEqual(data["attachments"], [])

    def test_in_reply_to_field(self):
        data = parse_email(_raw(in_reply_to="<prev@ex.com>"))
        self.assertEqual(data["in_reply_to"], "<prev@ex.com>")

    def test_empty_subject_falls_back_to_empty_string(self):
        m = EmailMessage()
        m["From"] = "a@ex.com"
        m["To"] = "b@ex.com"
        m["Message-ID"] = "<no-subj@ex>"
        m.set_content("body")
        data = parse_email(m.as_bytes())
        self.assertEqual(data["subject"], "")


class TestFindTicket(TestCase):
    def test_plus_token_matches(self):
        ticket = Ticket.objects.create(
            title="Ticket one",
            description="desc",
            created_by=User.objects.create_user("u", "u@ex.com", "x"),
        )
        parsed = parse_email(_raw(to=f"support+{ticket.pk}@jackil.local"))
        self.assertEqual(find_ticket(parsed), ticket)

    def test_subject_token_matches(self):
        ticket = Ticket.objects.create(
            title="Ticket two",
            description="desc",
            created_by=User.objects.create_user("u", "u@ex.com", "x"),
        )
        parsed = parse_email(_raw(subject=f"[#{ticket.pk}] Re: hello"))
        self.assertEqual(find_ticket(parsed), ticket)

    def test_no_token_returns_none(self):
        parsed = parse_email(_raw(subject="Just a question"))
        self.assertIsNone(find_ticket(parsed))

    def test_plus_token_not_found_returns_none(self):
        parsed = parse_email(_raw(to="support+9999@jackil.local"))
        self.assertIsNone(find_ticket(parsed))


class TestGetOrCreateRequester(TestCase):
    def test_creates_customer_user(self):
        user = get_or_create_requester("new@example.com", "New User")
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user.role, "customer")
        self.assertTrue(user.has_usable_password() is False)
        self.assertEqual(user.first_name, "New")
        self.assertEqual(user.last_name, "User")

    def test_reuses_existing_user(self):
        addr = "same@example.com"
        user1 = get_or_create_requester(addr, "First Name")
        user2 = get_or_create_requester(addr, "Other Name")
        self.assertEqual(user1.pk, user2.pk)

    def test_generates_unique_username(self):
        User.objects.create_user("user", "other@example.com", "x")
        user = get_or_create_requester("user@example.com", "User Name")
        self.assertTrue(user.username.startswith("user"))
        self.assertNotEqual(user.username, "user")

    def test_special_chars_in_email_local_part(self):
        user = get_or_create_requester("john.doe+tag@example.com", "")
        self.assertEqual(user.email, "john.doe+tag@example.com")
        self.assertIn("john.doe", user.username)


class TestIngestEmail(TestCase):
    def test_new_email_opens_ticket(self):
        result = ingest_email(
            _raw(
                sender="newperson@example.com",
                to="support@jackil.local",
                subject="Printer is broken",
                body="It jams every time.",
            )
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["ticket"].source, "email")
        self.assertEqual(result["ticket"].requester_email, "newperson@example.com")
        self.assertEqual(result["ticket"].status, "open")
        msg = result["message"]
        self.assertEqual(msg.kind, "incoming_email")
        self.assertEqual(msg.is_public, True)
        self.assertEqual(msg.from_email, "newperson@example.com")

    def test_plus_token_threads_onto_ticket(self):
        ticket = Ticket.objects.create(
            title="Existing",
            description="desc",
            created_by=User.objects.create_user("u", "u@ex.com", "x"),
        )
        result = ingest_email(_raw(sender="a@ex.com", to=f"support+{ticket.pk}@jackil.local"))
        self.assertEqual(result["status"], "appended")
        self.assertEqual(result["ticket"].pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_subject_token_threads_onto_ticket(self):
        ticket = Ticket.objects.create(
            title="Existing",
            description="desc",
            created_by=User.objects.create_user("u", "u@ex.com", "x"),
        )
        result = ingest_email(_raw(sender="a@ex.com", subject=f"[#{ticket.pk}] Re: hello"))
        self.assertEqual(result["status"], "appended")
        self.assertEqual(result["ticket"].pk, ticket.pk)

    def test_duplicate_message_id_skipped(self):
        result1 = ingest_email(_raw(mid="<dup@ex>"))
        self.assertEqual(result1["status"], "created")
        result2 = ingest_email(_raw(mid="<dup@ex>"))
        self.assertEqual(result2["status"], "duplicate")
        self.assertIsNone(result2["message"])

    def test_attachment_is_stored(self):
        result = ingest_email(_raw_with_attachment())
        self.assertEqual(result["ticket"].attachments.count(), 1)
        att = result["ticket"].attachments.first()
        self.assertEqual(att.original_name, "file.txt")
        self.assertGreater(att.size, 0)

    def test_reply_reopens_closed_ticket(self):
        ticket = Ticket.objects.create(
            title="Closed ticket",
            description="desc",
            created_by=User.objects.create_user("u", "u@ex.com", "x"),
            status="closed",
        )
        result = ingest_email(_raw(sender="a@ex.com", to=f"support+{ticket.pk}@jackil.local"))
        self.assertEqual(result["status"], "appended")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "open")
        self.assertIsNone(ticket.closed_at)

    def test_no_subject_creates_no_subject_title(self):
        result = ingest_email(_raw(subject="", body="some body"))
        self.assertEqual(result["ticket"].title, "(no subject)")

    def test_subject_token_stripped_from_title(self):
        result = ingest_email(_raw(sender="a@ex.com", subject="[#99] Re: Problem", body="desc"))
        self.assertEqual(result["ticket"].title, "Re: Problem")


class TestPollInboxCommand(TestCase):
    @patch("apps.inbox.management.commands.poll_inbox.Command._poll_one")
    def test_no_inboxes_no_output(self, mock_poll):
        from django.core.management import call_command

        mock_poll.return_value = 0
        call_command("poll_inbox")
        mock_poll.assert_not_called()

    @patch("apps.inbox.management.commands.poll_inbox.Command._poll_one")
    def test_polls_active_inboxes_with_host(self, mock_poll):
        from django.core.management import call_command

        from apps.inbox.models import Inbox

        Inbox.objects.create(
            name="Test",
            email_address="test@jackil.local",
            active=True,
            imap_host="mail.test.com",
            imap_port=993,
            imap_use_ssl=True,
            imap_password="pass",
        )
        mock_poll.return_value = 3
        call_command("poll_inbox")
        mock_poll.assert_called()
        inbox = Inbox.objects.first()
        self.assertIn("ok: 3 message(s)", inbox.last_poll_status)

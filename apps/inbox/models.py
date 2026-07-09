from django.core.mail import get_connection
from django.db import models
from django.utils import timezone


class Inbox(models.Model):
    name = models.CharField(max_length=120)
    email_address = models.EmailField(unique=True)
    is_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    # Outbound (SMTP)
    smtp_host = models.CharField(max_length=255, blank=True, default="")
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=255, blank=True, default="")
    # SECURITY TODO: encrypt at rest (e.g. django-fernet-fields)
    smtp_password = models.CharField(max_length=255, blank=True, default="")
    smtp_use_tls = models.BooleanField(default=True)

    # Inbound (IMAP) — used in phase-04
    imap_host = models.CharField(max_length=255, blank=True, default="")
    imap_port = models.PositiveIntegerField(default=993)
    imap_username = models.CharField(max_length=255, blank=True, default="")
    imap_password = models.CharField(max_length=255, blank=True, default="")
    imap_use_ssl = models.BooleanField(default=True)
    imap_folder = models.CharField(max_length=120, default="INBOX")

    signature = models.TextField(blank=True, default="")
    last_polled_at = models.DateTimeField(null=True, blank=True)
    last_poll_status = models.CharField(max_length=255, blank=True, default="")
    last_seen_uid = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "inboxes"
        ordering = ["-is_default", "name"]

    def __str__(self):
        return f"{self.name} <{self.email_address}>"

    @classmethod
    def get_default(cls):
        return cls.objects.filter(active=True).order_by("-is_default", "id").first()

    def reply_to_address(self, ticket_id):
        """Plus-addressed reply token: support+<id>@domain."""
        local, _, domain = self.email_address.partition("@")
        return f"{local}+{ticket_id}@{domain}"

    def get_connection(self):
        """SMTP connection for this inbox, or the default backend (console in
        dev) when no SMTP host is configured."""
        if self.smtp_host:
            return get_connection(
                backend="django.core.mail.backends.smtp.EmailBackend",
                host=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_username,
                password=self.smtp_password,
                use_tls=self.smtp_use_tls,
            )
        return get_connection()

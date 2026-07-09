from django.db import models
from django.utils import timezone


class Ticket(models.Model):
    PRIORITY_CHOICES = [
        ("critical", "Critical"),
        ("high", "High"),
        ("medium", "Medium"),
        ("low", "Low"),
    ]

    STATUS_CHOICES = [
        ("open", "Open"),
        ("in_progress", "In Progress"),
        ("pending", "Pending"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="medium")
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="created_tickets"
    )
    assigned_to = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    assigned_users = models.ManyToManyField(
        "accounts.User", blank=True, related_name="managed_tickets"
    )
    department = models.ForeignKey(
        "accounts.Department", on_delete=models.SET_NULL, null=True, blank=True
    )
    tags = models.TextField(blank=True, default="")
    SOURCE_CHOICES = [("web", "Web"), ("email", "Email"), ("api", "API")]
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="web")
    requester_email = models.EmailField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} (#{self.pk})"

    @property
    def tag_list(self):
        if self.tags:
            return [t.strip() for t in self.tags.split(",")]
        return []

    @property
    def progress(self):
        if self.status == "closed":
            return 100
        if self.status == "resolved":
            return 80
        if self.status == "pending":
            return 50
        if self.status == "in_progress":
            return 30
        return 10

    @property
    def color_class(self):
        colors = {"critical": "coral", "high": "rose", "medium": "lavender", "low": "mint"}
        return colors.get(self.priority, "lavender")


class TicketComment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Comment by {self.author} on #{self.ticket.pk}"


class TicketMessage(models.Model):
    KIND_CHOICES = [
        ("reply", "Reply"),  # public, visible to the customer
        ("note", "Internal note"),  # agents/admins only
        ("incoming_email", "Incoming email"),
        ("outgoing_email", "Outgoing email"),
        ("system", "System event"),  # audit trail (assigned, status change…)
    ]
    EMAIL_STATUS_CHOICES = [
        ("", "—"),
        ("queued", "Queued"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    ]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_messages",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="reply")
    body = models.TextField(blank=True, default="")
    is_public = models.BooleanField(default=True)
    # Email metadata (blank for non-email messages)
    from_email = models.CharField(max_length=255, blank=True, default="")
    to_email = models.CharField(max_length=255, blank=True, default="")
    message_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    in_reply_to = models.CharField(max_length=255, blank=True, default="")
    email_status = models.CharField(
        max_length=10, choices=EMAIL_STATUS_CHOICES, blank=True, default=""
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} on #{self.ticket_id}"

    @property
    def is_email(self):
        return self.kind in ("incoming_email", "outgoing_email")

    @property
    def author_display(self):
        if self.author:
            return self.author.get_full_name() or self.author.username
        if self.from_email:
            return self.from_email
        return "System"


def attachment_upload_path(instance, filename):
    return f"attachments/ticket_{instance.ticket_id}/{filename}"


class Attachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    message = models.ForeignKey(
        TicketMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    file = models.FileField(upload_to=attachment_upload_path)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True, default="")
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.original_name

    @property
    def size_display(self):
        n = self.size
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024

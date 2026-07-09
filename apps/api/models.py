import secrets

from django.db import models


class ApiKey(models.Model):
    name = models.CharField(max_length=120)
    key = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="api_keys")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.masked})"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = self.generate_key()
        super().save(*args, **kwargs)

    @property
    def masked(self):
        return f"{self.key[:6]}…{self.key[-4:]}" if self.key else ""

    @staticmethod
    def generate_key():
        return secrets.token_urlsafe(32)


class Webhook(models.Model):
    EVENT_CHOICES = [
        ("ticket.created", "Ticket created"),
        ("ticket.updated", "Ticket updated"),
    ]
    name = models.CharField(max_length=120)
    url = models.URLField(max_length=500)
    event = models.CharField(max_length=30, choices=EVENT_CHOICES, default="ticket.created")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=60, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} → {self.url}"

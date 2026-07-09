from django.db import models


class Macro(models.Model):
    """A canned response agents can insert into a reply."""

    name = models.CharField(max_length=120)
    body = models.TextField()
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    is_shared = models.BooleanField(default=True, help_text="Available to all agents.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AutomationRule(models.Model):
    """A trigger→conditions→actions rule applied to tickets on events.

    ``conditions`` is a JSON list of ``{"field", "op", "value"}`` (all must
    match). ``actions`` is a JSON list of ``{"type", "value"}``.
    """

    TRIGGER_CHOICES = [
        ("on_create", "Ticket created"),
        ("on_reply", "Reply added"),
        ("on_status_change", "Status changed"),
    ]

    name = models.CharField(max_length=120)
    trigger = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default="on_create")
    conditions = models.JSONField(default=list, blank=True)
    actions = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    run_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name

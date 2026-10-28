import uuid

from django.conf import settings
from django.db import models


class Report(models.Model):
    """A named, saved set of report cards over chosen sources and a range."""

    #: The ranges the builder offers.
    RANGES = (7, 14, 30, 90, 180, 365)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports",
    )
    shared = models.BooleanField(default=False)
    departments = models.ManyToManyField("accounts.Department", blank=True, related_name="+")
    projects = models.ManyToManyField("projects.Project", blank=True, related_name="+")
    saved_views = models.ManyToManyField("tickets.SavedView", blank=True, related_name="+")
    range_days = models.PositiveIntegerField(default=30)
    #: [{"kind", "chart"?, "title"?, "x_label"?, "y_label"?, "x"?, "y"?, "w"?, "h"?}]
    widgets = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

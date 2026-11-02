from django.conf import settings
from django.db import models


class DynamicLink(models.Model):
    """One directed typed edge between two objects, addressed by type and id."""

    source_type = models.CharField(max_length=40)
    source_id = models.CharField(max_length=64)
    target_type = models.CharField(max_length=40)
    target_id = models.CharField(max_length=64)
    relation = models.CharField(max_length=32, default="relates_to")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    #: Remote (vigil:*) targets only: the last name we saw, so a link can still
    #: be named when the other app is unreachable.
    target_label_cache = models.CharField(max_length=200, blank=True, default="")
    target_cached_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("source_type", "source_id", "target_type", "target_id", "relation"),
                name="uniq_dynamic_link",
            ),
        ]
        indexes = [
            models.Index(fields=("source_type", "source_id")),
            models.Index(fields=("target_type", "target_id")),
        ]

    def __str__(self) -> str:
        return f"{self.source_type}:{self.source_id} -{self.relation}-> {self.target_type}:{self.target_id}"

from django.db import models


class SiteBranding(models.Model):
    """Singleton white-label settings for this Jackil install (row pk=1)."""

    product_name = models.CharField(max_length=60, default="Jackil")
    tagline = models.CharField(max_length=120, default="IT Ticket Management")
    accent = models.CharField(max_length=20, default="lavender")

    def __str__(self):
        return self.product_name

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

from django.db import models


class LicenceRecord(models.Model):
    """Singleton (pk=1): the last licence answer Jackil got from its Vigil."""

    blob = models.TextField(blank=True, default="")
    vigil_instance = models.CharField(max_length=64, blank=True, default="")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True, default="")

    def __str__(self):
        return f"licence ({self.vigil_instance or 'no Vigil'})"

    @classmethod
    def get_solo(cls):
        solo, _created = cls.objects.get_or_create(pk=1)
        return solo

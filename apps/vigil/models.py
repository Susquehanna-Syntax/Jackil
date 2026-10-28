import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(("vigil-key:" + settings.SECRET_KEY).encode()).digest()
    )
    return Fernet(key)


class VigilConnection(models.Model):
    """Singleton (pk=1): where Vigil is and the key Jackil reads it with."""

    base_url = models.URLField(blank=True, default="")
    key_encrypted = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=False)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_ok = models.BooleanField(default=False)
    last_message = models.CharField(max_length=300, blank=True, default="")
    vigil_version = models.CharField(max_length=40, blank=True, default="")

    def __str__(self):
        return self.base_url or "Vigil (not configured)"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def set_key(self, raw: str):
        raw = raw.strip() if raw else ""
        self.key_encrypted = _fernet().encrypt(raw.encode()).decode() if raw else ""

    def get_key(self) -> str:
        if not self.key_encrypted:
            return ""
        try:
            return _fernet().decrypt(self.key_encrypted.encode()).decode()
        except InvalidToken:
            return ""

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.get_key())

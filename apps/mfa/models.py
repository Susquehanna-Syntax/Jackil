"""Models for ``apps/mfa``. Self-contained: no import from any other app.

The TOTP secret is encrypted at rest so a stolen database backup cannot
enrol an attacker's authenticator; see ``_fernet`` for the key derivation.
"""

import base64
import hashlib

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import models


def _fernet():
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(
        hashlib.sha256(b"sqsy-mfa:" + settings.SECRET_KEY.encode()).digest()
    )
    return Fernet(key)


class MfaProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa"
    )
    totp_secret_encrypted = models.BinaryField(blank=True, null=True)
    totp_confirmed_at = models.DateTimeField(blank=True, null=True)
    last_totp_code = models.CharField(max_length=12, blank=True)
    last_totp_used_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def totp_secret(self) -> str:
        """The base32 secret, decrypted. Empty when no authenticator is set."""
        if not self.totp_secret_encrypted:
            return ""
        return _fernet().decrypt(bytes(self.totp_secret_encrypted)).decode()

    @totp_secret.setter
    def totp_secret(self, value: str) -> None:
        self.totp_secret_encrypted = (
            _fernet().encrypt(value.encode()) if value else None
        )

    def confirmed(self) -> bool:
        return bool(self.totp_confirmed_at and self.totp_secret)

    def clear_secret(self) -> None:
        """Forget the authenticator. Saves only if there was one to forget."""
        if self.totp_secret_encrypted is None and self.totp_confirmed_at is None:
            return
        self.totp_secret_encrypted = None
        self.totp_confirmed_at = None
        self.last_totp_code = ""
        self.last_totp_used_at = None
        self.save()

    def __str__(self) -> str:
        return f"mfa profile for {self.user_id}"


def _attempt_indexes():
    return [models.Index(fields=("user", "created_at"))]


class TotpAttempt(models.Model):
    """One TOTP/recovery-code guess. Rows exist only to count failures."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="mfa_attempts")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = _attempt_indexes()


class RecoveryCode(models.Model):
    """A one-time code that signs someone in when they lost their device.

    Stored hashed like a password; shown in plain text exactly once.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="recovery_codes")
    code_hash = models.CharField(max_length=128)
    used_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def new(cls, user, plain: str) -> "RecoveryCode":
        return cls.objects.create(user=user, code_hash=make_password(plain))

    def __str__(self) -> str:
        return f"recovery code for {self.user_id}"


class SecurityKey(models.Model):
    """A registered WebAuthn authenticator — security key or platform passkey.

    The credential id and public key are the raw CBOR/COSE bytes the library
    hands back; both are opaque to us and only ever passed back into it.
    ``sign_count`` is what makes a cloned authenticator detectable: the library
    refuses an assertion whose count has not advanced past what we stored.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="security_keys"
    )
    name = models.CharField(max_length=60)
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveBigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"key {self.name!r} <user {self.user_id}>"


class KeyToken(models.Model):
    """A one-time confirmation from a security-key tap. Spent by deleting the
    row: the database says exactly once that it removed it, so two requests
    racing on one token cannot both pass a gate with it."""

    digest = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    session_key = models.CharField(max_length=64, blank=True, default="")
    expires_at = models.DateTimeField()

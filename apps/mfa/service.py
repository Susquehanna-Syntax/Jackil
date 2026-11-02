"""Clears a user's second factors so they can set them up again. The
staff-only caller lives in the console; nothing here checks permission."""

from .models import MfaProfile, SecurityKey, TotpAttempt


def reset(user) -> None:
    """Delete the authenticator secret, every recovery code and security key,
    and the failed attempt rows. The user's password is untouched."""
    profile = MfaProfile.objects.filter(user=user).first()
    if profile is not None:
        profile.delete()
    user.recovery_codes.all().delete()
    SecurityKey.objects.filter(user=user).delete()
    TotpAttempt.objects.filter(user=user).delete()

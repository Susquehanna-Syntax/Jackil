"""SAML configuration and the identity mapping.

Local username/password sign-in always keeps working: SAML is additive,
and an admin can always get in when the identity provider is down.
"""

from django.conf import settings as django_settings
from django.db import models


class SamlConfig(models.Model):
    """Singleton (pk=1): the identity provider this Jackil signs people in with."""

    ROLE_CHOICES = [("customer", "Customer"), ("agent", "Support Assistant")]

    enabled = models.BooleanField(default=False)
    idp_entity_id = models.CharField(max_length=300, blank=True, default="")
    idp_sso_url = models.URLField(blank=True, default="")
    idp_x509_cert = models.TextField(blank=True, default="", help_text="PEM body or full PEM")
    email_attribute = models.CharField(max_length=120, blank=True, default="email")
    name_attribute = models.CharField(max_length=120, blank=True, default="name")
    new_user_role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="customer")
    allow_new_users = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"saml:{self.idp_entity_id or '(unset)'} ({'on' if self.enabled else 'off'})"

    @classmethod
    def get_solo(cls):
        solo, _created = cls.objects.get_or_create(pk=1)
        return solo


class SamlIdentity(models.Model):
    """Maps an identity provider NameID to a local user.

    The mapping row — never a username match — is what lets SAML adopt an
    install safely: an admin links accounts by hand, and creating a local
    "alice" can never be claimed by the IdP's alice.
    """

    user = models.OneToOneField(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saml_identity",
    )
    name_id = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user} ↔ saml:{self.name_id}"

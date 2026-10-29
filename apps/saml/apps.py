from django.apps import AppConfig


class SamlConfigAppConfig(AppConfig):
    """``name`` stays ``apps.saml``; the class is not called ``SamlConfig`` —
    that name is the model, and Django's app registry keys on the label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.saml"
    verbose_name = "SAML SSO"

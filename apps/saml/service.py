"""Is SAML on, and what do we tell OneLogin about our identity provider?

Two conditions have to hold: the licence includes SQSY Business, and an
admin has switched SAML on and filled in the three things that make an
IdP talk to us. Either one off means the whole feature is absent — no
button, no URLs, no metadata.
"""

from __future__ import annotations

import re

from config.features import feature_enabled

_PEM_EDGE = re.compile(r"-----BEGIN CERTIFICATE-----|-----END CERTIFICATE-----")


def active() -> bool:
    """True when SAML sign-in is available on this install. Never raises."""
    if not feature_enabled("saml"):
        return False
    from apps.saml.models import SamlConfig

    cfg = SamlConfig.objects.filter(pk=1).first()
    if cfg is None or not cfg.enabled:
        return False
    return bool(cfg.idp_entity_id and cfg.idp_sso_url and cfg.idp_x509_cert)


def sp_entity_id(request) -> str:
    """Our Entity ID; settings_dict and the settings page must agree on it."""
    return _base(request) + "/saml/metadata/"


def acs_url(request) -> str:
    return _base(request) + "/saml/acs/"


def _base(request) -> str:
    return request.build_absolute_uri("/").rstrip("/")


def clean_cert(pem: str) -> str:
    """The base64 body of the certificate — OneLogin wants no PEM armour."""
    return "".join("".join(_PEM_EDGE.split(pem or "")).split())


def settings_dict(request) -> dict:
    """The OneLogin settings structure for this request's host."""
    from apps.saml.models import SamlConfig

    cfg = SamlConfig.get_solo()
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": sp_entity_id(request),
            "assertionConsumerService": {
                "url": acs_url(request),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
        "idp": {
            "entityId": cfg.idp_entity_id,
            "singleSignOnService": {
                "url": cfg.idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": clean_cert(cfg.idp_x509_cert),
        },
        "security": {
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "requestedAuthnContext": False,
        },
    }

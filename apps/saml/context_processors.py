from apps.saml import service


def saml(request):
    """Exposes ``saml_enabled`` so the login template can show the SSO button."""
    return {"saml_enabled": service.active()}

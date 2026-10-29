"""The SAML flow: start → identity provider → assertion consumer service.

Failure philosophy, copied from Civil SSO: every failure lands on the
ordinary login page (``?saml=failed``). A down or misconfigured IdP must
never produce an error page or lock out local sign-in.
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings

from apps.console.decorators import admin_required
from apps.licensing.gates import business_page
from apps.saml import service
from apps.saml.forms import SamlConfigForm
from apps.saml.models import SamlConfig, SamlIdentity

logger = logging.getLogger("saml")

_NEXT_SESSION_KEY = "saml_next"


def prepare_request(request):
    return {
        "https": "on" if request.is_secure() else "off",
        "http_host": request.get_host(),
        "script_name": request.path,
        "get_data": request.GET.copy(),
        "post_data": request.POST.copy(),
    }


def login_start(request):
    """Kick off SSO: remember a safe ``next``, bounce to the IdP."""
    if not service.active():
        raise Http404

    nxt = request.GET.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        request.session[_NEXT_SESSION_KEY] = nxt
    auth = OneLogin_Saml2_Auth(prepare_request(request), service.settings_dict(request))
    return redirect(auth.login(return_to=nxt or None))


@csrf_exempt
@require_POST
def acs(request):
    """The assertion consumer service: verify, map or provision, log in."""
    if not service.active():
        raise Http404

    def fail(reason: str):
        logger.warning("SAML sign-in failed: %s", reason)
        return redirect("/login/?saml=failed")

    cfg = SamlConfig.get_solo()
    auth = OneLogin_Saml2_Auth(prepare_request(request), service.settings_dict(request))
    try:
        auth.process_response()
    except Exception as malformed:  # junk in from the IdP is a failed sign-in, not a 500
        return fail(f"malformed assertion: {malformed}")
    errors = auth.get_errors()
    if errors or not auth.is_authenticated():
        return fail(auth.get_last_error_reason() or "; ".join(errors) or "no assertion")

    name_id = auth.get_nameid()
    if not name_id:
        return fail("assertion carried no NameID")
    attributes = auth.get_attributes()

    identity = SamlIdentity.objects.filter(name_id=name_id).select_related("user").first()
    if identity is None:
        if not cfg.allow_new_users:
            return fail(f"{name_id} is not a known identity and new users are not allowed")
        user = _provision_user(cfg, name_id, attributes)
        identity = SamlIdentity.objects.create(user=user, name_id=name_id)
    user = identity.user
    if not user.is_active:
        return fail(f"local user {user.pk} is inactive")

    login(request, user)
    return redirect(request.session.pop(_NEXT_SESSION_KEY, "") or "/")


def metadata(request):
    """Our service-provider metadata, for pasting into the IdP."""
    if not service.active():
        raise Http404

    xml = OneLogin_Saml2_Settings(service.settings_dict(request), sp_validation_only=True)
    return HttpResponse(xml.get_sp_metadata(), content_type="application/samlmetadata+xml")


def saml_settings(request):
    locked = business_page(request, "saml", what="SAML sign-in")
    if locked is not None:
        return locked
    return _settings_view(request)


@admin_required
def _settings_view(request):
    cfg = SamlConfig.get_solo()
    if request.method == "POST":
        form = SamlConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            form.save()
            messages.success(request, "SAML settings saved.")
        else:
            for error in sorted(
                text for field_errors in form.errors.values() for text in field_errors
            ):
                messages.error(request, error)
        return redirect("console:saml_settings")

    return render(
        request,
        "saml/settings.html",
        {
            "form": SamlConfigForm(instance=cfg),
            "config": cfg,
            "entity_id": service.sp_entity_id(request),
            "acs_url": service.acs_url(request),
            "metadata_url": service.sp_entity_id(request),
            "section": "saml",
        },
    )


def _attribute(attributes: dict, key: str) -> str:
    values = attributes.get(key) or []
    return str(values[0]) if values else ""


def _provision_user(cfg, name_id: str, attributes: dict):
    """First SSO sign-in for this human: create a local user.

    Username prefers the assertion's email local part, dodging collisions
    with a short suffix — an existing local "alice" is a DIFFERENT account
    than the IdP's alice unless an admin links them by hand.
    """
    User = get_user_model()
    email = _attribute(attributes, cfg.email_attribute)
    base = ((email.split("@")[0] if email else "") or name_id)[:140] or "saml-user"
    username = base
    n = 2
    while User.objects.filter(username=username).exists():
        username = f"{base}-{n}"
        n += 1
    user = User.objects.create_user(username=username, email=email, role=cfg.new_user_role)
    user.set_unusable_password()  # the IdP is this account's only way in
    name = _attribute(attributes, cfg.name_attribute).strip()
    if name:
        user.first_name = name.split(" ")[0][:150]
        user.last_name = " ".join(name.split(" ")[1:])[:150]
    user.save()
    logger.info("provisioned local user %s for saml:%s", username, name_id)
    return user

"""The second step of signing in: every account proves a second factor.

A correct password no longer signs anyone in. It parks the user's id in the
session as *pending* and sends the browser to ``/mfa/verify/``, where one of
two things finishes the sign-in:

  * a six-digit TOTP code, or an unused recovery code,
  * for an account with neither, enrolling TOTP right there — scan, confirm a
    code — before Civil opens. The enrolment code IS the second factor, so the
    recovery codes handed out afterwards cannot open a door on their own; they
    are shown once, to be read, and not asked for again until the phone is gone.

``auth.login`` is only ever called from here, after a factor checks out, so a
pending session is an anonymous session in every other view: the API, the
console and SSO all see no user.

Guesses count against the same per-user code limit the security page uses,
so the second step cannot be brute-forced from the sign-in page either.
"""

import json
import time

from django.contrib import auth, messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)

from . import conf, keys, recovery
from .models import MfaProfile
from .qr import totp_qr_svg
from .totp import (
    _clear_totp_attempts,
    _totp_attempt_allowed,
    confirm_secret,
    consume_totp,
    generate_secret,
    has_second_factor,
    otpauth_uri,
)

PENDING_KEY = "mfa_pending"
ENROL_KEY = "mfa_enrol_secret"
FRESH_CODES_KEY = "mfa:fresh_codes"
AFTER_CODES_KEY = "mfa:after_codes"
#: Whose fresh recovery codes and enrolment secret these are. Both are only
#: ever honoured for that same signed-in user.
OWNER_KEY = "mfa:owner"
#: Set when a signed-in user confirms with their current factor and is handed
#: WebAuthn creation options; only the registration from that same user uses it.
KEY_GATE_KEY = "mfa:key_gate"
#: Long enough to find a phone; short enough that a password typed on a shared
#: machine and walked away from does not stay half signed in.
PENDING_SECONDS = 300

TOO_MANY = "Too many wrong codes. Wait a few minutes and try again."
KEY_FAILED = "That key was not accepted. Try again or use a code."


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def _body(request) -> dict:
    """The JSON body, or ``{}`` when there wasn't one. A credential the browser
    never sent is an ordinary wrong answer, not a server error."""
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def safe_next(request, candidate: str) -> str:
    """Same-host relative targets only; anything else is an open redirect."""
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}
    ):
        return candidate
    return "/"


def begin(request, user, next_url: str = "/", backend: str = ""):
    """Park ``user`` as pending and send the browser to the second step."""
    for key in (ENROL_KEY, FRESH_CODES_KEY, AFTER_CODES_KEY, OWNER_KEY, KEY_GATE_KEY):
        request.session.pop(key, None)
    request.session[PENDING_KEY] = {
        "uid": str(user.pk),
        "exp": time.time() + PENDING_SECONDS,
        "next": safe_next(request, next_url),
        "backend": backend or getattr(user, "backend", "")
        or "django.contrib.auth.backends.ModelBackend",
    }
    return redirect("mfa:verify")


def _pending(request):
    """(user, state) for a live pending sign-in, or (None, None)."""
    state = request.session.get(PENDING_KEY) or {}
    if not state or _expired(state):
        _forget(request)
        return None, None
    user = get_user_model().objects.filter(pk=state.get("uid"), is_active=True).first()
    if user is None:
        _forget(request)
        return None, None
    return user, state


def _expired(state) -> bool:
    """Whether a parked sign-in outlived ``PENDING_SECONDS``.

    The deadline is wall-clock (``time.time()``) because that is the clock the
    one-time codes are cut on; comparing it against anything else — an aware
    datetime, say — would expire every pending sign-in at once or none at all.
    """
    return not state or time.time() >= (state.get("exp") or 0)


def _forget(request) -> None:
    request.session.pop(PENDING_KEY, None)
    request.session.pop(ENROL_KEY, None)


def _finish(request, user, state) -> str:
    """Sign in for real. Returns where to go next."""
    _forget(request)
    auth.login(request, user, backend=state["backend"])
    return state.get("next") or "/"


def _keys_offered(request, user) -> bool:
    """Whether to offer a key tap here: keys configured for this install, and
    this account has at least one."""
    _rp_id, origin = keys.relying_party(request)
    return keys.secure_context(origin) and keys.user_has_keys(user)


def _confirming(request) -> bool:
    """Whether this key request is a signed-in person confirming an action on
    the security page rather than a pending sign-in finishing itself.

    Django's ``login_required`` answers an anonymous *POST* with a redirect to
    the sign-in page, which a fetch call cannot do anything with — so the same
    endpoint serves both cases and says so in JSON when there is nobody here.
    """
    return request.GET.get("confirm") == "1"


@require_POST
def verify_key_options(request):
    """Assertion options: for the pending sign-in, or, with ``?confirm=1``, for
    the signed-in user confirming something. 404 without either — nothing is
    offered before a password has been accepted."""
    user = request.user if _confirming(request) else _pending(request)[0]
    if user is None or not user.is_authenticated:
        return _json_error("Your sign-in expired. Start again.", 404)
    try:
        return JsonResponse(keys.authentication_options(request, user=user))
    except ValueError as exc:
        return _json_error(str(exc))


@require_POST
def verify_key(request):
    """Verify the tap and finish the sign-in in the same request.

    ``?confirm=1`` is the other use of the same ceremony: a signed-in person
    confirming an action on the security page, for whom there is no pending
    sign-in to finish — that request answers with the one-time token, which
    the page sends back as the ``code`` field. Either way a guess against this
    account is recorded in the counter a typed code uses, so the two together
    still get five tries.
    """
    confirming = _confirming(request)
    user, state = (request.user, None) if confirming else _pending(request)
    if user is None or not user.is_authenticated:
        return _json_error("Your sign-in expired. Start again.", 404)
    if not keys.user_has_keys(user):
        return _json_error("No security key is set up for this account.")
    if not _totp_attempt_allowed(user):
        return _json_error(TOO_MANY, 429)
    try:
        token = keys.authenticate(
            request,
            _body(request).get("credential"),
            user=user,
        )
    except (TypeError, ValueError, InvalidAuthenticationResponse) as exc:
        return _json_error(str(exc) or KEY_FAILED)
    _clear_totp_attempts(user)
    if confirming:
        # Nothing to sign in: the token is what stands in for a code, and it is
        # spent by whichever action the page goes on to confirm.
        return JsonResponse({"token": token})
    if not keys.consume_key_token(request, user, token):
        return _json_error(KEY_FAILED)
    return JsonResponse({"next": _finish(request, user, state)})


def verify(request):
    """The second step. Enrolment for a factor-less account happens on the
    setup page, which confirms a code before it replaces anything — and signs
    a pending user in once that code checks out."""
    user, state = _pending(request)
    if user is None:
        return redirect(conf.login_url())

    if not has_second_factor(user):
        return setup(request)

    error = None
    if request.method == "POST":
        code = request.POST.get("code", "")
        if code.strip().startswith(keys.KEY_TOKEN_PREFIX):
            # A key token is handed over by the key button below, never typed.
            error = "Enter the six-digit code from your authenticator app."
        else:
            ok, err = consume_totp(user, code, request)
            if ok:
                return redirect(_finish(request, user, state))
            error = err

    return render(
        request,
        "mfa/verify.html",
        {
            "error": error,
            "username": user.get_username(),
            "keys": _keys_offered(request, user),
            "login_url": conf.login_url(),
        },
        status=400 if error else 200,
    )


def codes(request):
    """The fresh recovery codes — shown once, to the signed-in user they were
    made for, then gone from the session. This page never signs anyone in:
    by the time codes exist, the code that made them has already done that."""
    fresh = request.session.get(FRESH_CODES_KEY)
    owner = request.session.get(OWNER_KEY)
    if not (request.user.is_authenticated and fresh and owner == str(request.user.pk)):
        for key in (FRESH_CODES_KEY, AFTER_CODES_KEY):
            request.session.pop(key, None)
        return redirect("mfa:security" if request.user.is_authenticated else conf.login_url())
    if request.method == "POST":
        request.session.pop(FRESH_CODES_KEY, None)
        after = request.session.pop(AFTER_CODES_KEY, None)
        return redirect(after or "mfa:security")
    return render(request, "mfa/codes.html", {"codes": fresh, "pending": False})


class MfaLoginView(auth_views.LoginView):
    """The password step. A correct password only *starts* a sign-in."""

    def get_template_names(self):
        return [conf.login_template()]

    def form_valid(self, form):
        user = form.get_user()
        backend = getattr(user, "backend", "")
        if not conf.required(user) or backend in conf.trusted_backends():
            return super().form_valid(form)
        # Park the user as pending instead of signing them in.
        return begin(
            self.request,
            user,
            self.get_redirect_url() or self.get_default_redirect_url(),
            backend,
        )


# -- The signed-in security page ---------------------------------------------


def _confirmed(request, raw) -> bool:
    """Whether ``raw`` — a typed code or the ``wa_`` token a key tap handed
    back — is a factor this account holds right now."""
    ok, err = consume_totp(request.user, raw or "", request)
    if not ok:
        messages.error(request, err or "That code didn't match.")
    return ok


@login_required
def security(request):
    user = request.user
    profile = MfaProfile.objects.filter(user=user).first()
    has_authenticator = bool(profile is not None and profile.confirmed())
    if request.method == "POST" and has_authenticator:
        action = request.POST.get("action", "")
        if action == "codes":
            if _confirmed(request, request.POST.get("code")):
                request.session[FRESH_CODES_KEY] = recovery.make_codes(user)
                request.session[OWNER_KEY] = str(user.pk)
                return redirect("mfa:codes")
        elif action == "setup" and _confirmed(request, request.POST.get("code")):
            # The old secret stays until the new one checks out on setup, and
            # this secret is only good for this signed-in user.
            request.session[ENROL_KEY] = generate_secret()
            request.session[OWNER_KEY] = str(user.pk)
            return redirect("mfa:setup")

    _rp_id, origin = keys.relying_party(request)
    return render(
        request,
        "mfa/security_page.html",
        {
            "has_authenticator": has_authenticator,
            "recovery_remaining": recovery.remaining(user),
            "security_keys": user.security_keys.all(),
            "keys_available": keys.secure_context(origin),
            "keys_reason": keys.unavailable_reason(origin),
        },
    )


# -- Security keys on the security page ---------------------------------------


@login_required
@require_POST
def key_options(request):
    """Creation options — and the confirmation that entitles them.

    Adding a factor costs the factor you already have, so that a stolen session
    cannot enrol the attacker's key and pass every gate after it: the code (or
    the ``wa_`` token from a key tap) is checked here, once, and the finished
    ceremony has nothing else to prove. Keeping the confirmation in the session
    rather than in the browser is deliberate — what a page echoes back is worth
    nothing, whereas this cannot be forged or replayed by anyone but the user
    who spent their factor on it.

    The challenge lives in the session and is used once, so the registration
    must follow this call rather than precede it.
    """
    _rp_id, origin = keys.relying_party(request)
    reason = keys.unavailable_reason(origin)
    if reason:
        return _json_error(reason)
    # Say why keys are off before spending anyone's code on the question.
    if not _confirmed(request, _body(request).get("code")):
        request.session.pop(KEY_GATE_KEY, None)
        return _json_error("Confirm with your current code or key first.", 401)
    try:
        options = keys.registration_options(request)
    except ValueError as exc:
        return _json_error(str(exc))
    request.session[KEY_GATE_KEY] = str(request.user.pk)
    return JsonResponse(options)


@require_POST
@login_required
def key_register(request):
    """Verify the registration response and save the key, for a user who was
    handed options a moment ago — after confirming with their current factor.

    ``consume_totp`` spends the failed-guess counter as a side effect, so by
    the time somebody has burned it out this is a 401 rather than a 429: still
    refused, and nothing here counts against the limit again.
    """
    if request.session.pop(KEY_GATE_KEY, None) != str(request.user.pk):
        return _json_error("Ask for the key request again first.", 401)
    body = _body(request)
    try:
        key = keys.register(request, body.get("name"), body.get("credential"))
    except (TypeError, ValueError, InvalidRegistrationResponse) as exc:
        return _json_error(str(exc) or KEY_FAILED)
    return JsonResponse({"id": key.id, "name": key.name}, status=201)


@login_required
@require_POST
def key_delete(request, key_id: int):
    """Remove one of your own keys; anybody else's is a 404.

    Removing a factor costs a factor, and the last key can only go while an
    authenticator is still there to catch the account — otherwise the person
    would face their next sign-in with no factor left and no way back in.
    """
    key = request.user.security_keys.filter(pk=key_id).first()
    if key is None:
        return _json_error("No such security key.", 404)
    if not _confirmed(request, _body(request).get("code")):
        return _json_error("Confirm with your current code or key first.", 401)
    remaining = request.user.security_keys.exclude(pk=key.pk).count()
    profile = MfaProfile.objects.filter(user=request.user).first()
    if remaining == 0 and not (profile is not None and profile.confirmed()):
        return _json_error(
            "Set up an authenticator app before removing your last key.", 400
        )
    key.delete()
    return JsonResponse({"removed": key_id})


def setup(request):
    """A new authenticator, confirmed with a code before the old secret is
    replaced. A signed-in user arrives from the security page; a pending
    sign-in arrives from ``verify`` for an account with no factor yet.

    The confirm-before-replace order is what makes recovery codes generated
    during enrolment harmless on their own: they are shown, but the sign-in
    still waits for a code from the authenticator that was just enrolled.
    """
    if request.user.is_authenticated:
        # Replacing an authenticator: only after the security page checked a
        # current code and handed this user a secret. Never on demand.
        user, state = request.user, None
        secret = request.session.get(ENROL_KEY)
        if not secret or request.session.get(OWNER_KEY) != str(user.pk):
            return redirect("mfa:security")
    else:
        user, state = _pending(request)
        if user is None:
            return redirect(conf.login_url())
        # A password alone may enrol only an account that has no factor at
        # all; one that has a factor must use it.
        if has_second_factor(user):
            return redirect("mfa:verify")
        secret = request.session.get(ENROL_KEY)
        if not secret:
            secret = generate_secret()
            request.session[ENROL_KEY] = secret

    error = None
    if request.method == "POST":
        ok, error = confirm_secret(user, secret, request.POST.get("code", ""))
        if ok:
            request.session.pop(ENROL_KEY, None)
            # A new authenticator comes with a new set of recovery codes: the
            # old set may have been written down beside the phone just lost.
            codes = recovery.make_codes(user)
            after = "mfa:security"
            if state is not None:
                after = _finish(request, user, state)
            request.session[FRESH_CODES_KEY] = codes
            request.session[AFTER_CODES_KEY] = after
            request.session[OWNER_KEY] = str(user.pk)
            messages.success(request, "Authenticator set up.")
            return redirect("mfa:codes")

    return render(
        request,
        "mfa/setup.html",
        {
            "error": error,
            "totp_secret": secret,
            "login_url": conf.login_url(),
            "totp_qr_svg": totp_qr_svg(otpauth_uri(secret, user.get_username())),
        },
        status=400 if error else 200,
    )

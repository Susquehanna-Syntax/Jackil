"""Security keys and passkeys: adding one, tapping one, and what a key proves.

The ``webauthn`` package cannot be driven without a real authenticator, so the
ceremony's two verify calls — which are the signature check — are patched where
they are imported in ``apps.mfa.keys``. Everything else is exercised for real,
including the library's own parsing and its challenge comparison: the helpers
below read the issued challenge out of the session exactly as a browser reads it
out of the options, so a ceremony only completes if the session's challenge is
the one that gets answered.

These endpoints speak JSON both ways, so ``post`` sends a JSON string — the same
bytes the browser sends — and puts the server's own answer in the assertion text
when it isn't what the test expected.
"""

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now

from apps.mfa import keys, views
from apps.mfa.models import MfaProfile, RecoveryCode, SecurityKey, TotpAttempt
from apps.mfa.recovery import RECOVERY_CODE_COUNT, make_codes
from apps.mfa.tests import SECRET, STRONG, enroll
from apps.mfa.totp import generate_totp, has_second_factor

RP_ID = "civil.example.com"
PUBLIC_URL = "https://civil.example.com"
KEYS = {"MFA_PUBLIC_URL": PUBLIC_URL}
# The browser sends Origin on a POST; an assertion is accepted from the origin
# the page was served on, while enrolment stays bound to MFA_PUBLIC_URL alone.
BROWSER = {"HTTP_ORIGIN": PUBLIC_URL}

CRED_ID = b"\x01\x02key-id"
PUBLIC_KEY = b"\x04pubkey"


def client_data_json(ceremony: str, challenge: str) -> str:
    """What the authenticator signed: the ceremony and the challenge it was
    given. The library compares that challenge against the session's for real,
    before the patched signature check is ever reached."""
    return keys.bytes_to_base64url(
        json.dumps(
            {
                "type": f"webauthn.{ceremony}",
                "challenge": challenge,
                "origin": PUBLIC_URL,
            }
        ).encode()
    )


# CBOR for {"fmt": "none", "attStmt": {}, "authData": <37 zero bytes>}, which is
# what an attestation of "none" looks like; the library parses it on the way in.
ATTESTATION_OBJECT = keys.bytes_to_base64url(b"\xa3cfmtdnonehattStmt\xa0hauthDataB" + b"\x00" * 37)
AUTHENTICATOR_DATA = keys.bytes_to_base64url(b"\x00" * 37)


class _VerifiedRegistration:
    credential_id = CRED_ID
    credential_public_key = PUBLIC_KEY
    sign_count = 7


class _VerifiedAuthentication:
    new_sign_count = 8


def credential(raw_id=CRED_ID, ceremony="create", challenge=""):
    """The JSON shape a browser posts. ``challenge`` is the one the session was
    issued; the signature is never looked at — the patched verify would have."""
    return {
        "id": keys.bytes_to_base64url(raw_id),
        "rawId": keys.bytes_to_base64url(raw_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": client_data_json(ceremony, challenge),
            "attestationObject": ATTESTATION_OBJECT,
            "authenticatorData": AUTHENTICATOR_DATA,
            "signature": AUTHENTICATOR_DATA,
            "transports": ["usb"],
        },
    }


def key_fixture(user, name="Office key", raw_id=CRED_ID, public_key=PUBLIC_KEY):
    return SecurityKey.objects.create(
        user=user,
        name=name,
        credential_id=raw_id,
        public_key=public_key,
        sign_count=1,
        transports=["usb"],
    )


class _no_patch:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


class KeyTestCase(TestCase):
    """JSON posts that report the server's answer when it surprises a test."""

    def post(self, url, body=None, status=None, verify=None, **request):
        """POST JSON and check the status. The URL is written as the browser
        would write it, so a ``?confirm=1`` suffix reaches the view as a query
        string rather than as POST data."""
        patcher = (
            mock.patch.object(keys, "verify_authentication_response", return_value=verify)
            if verify is not None
            else _no_patch()
        )
        with patcher:
            response = self.client.post(
                url,
                json.dumps(body if body is not None else {}),
                content_type="application/json",
                **request,
            )
        if status is not None and response.status_code != status:
            self.fail(
                f"{url} answered {response.status_code}, expected {status}: "
                f"{response.content[:400]!r}"
            )
        return response

    def body(self, response):
        try:
            return response.json()
        except ValueError:
            self.fail(f"a {response.status_code} reply was not JSON: {response.content[:200]!r}")

    def challenge(self, session_key):
        """The challenge this session was just issued — what a browser sees."""
        return self.client.session[session_key]["challenge"]

    def add_key(self, name="Office key", raw_id=CRED_ID):
        """POST /mfa/keys/ answering the challenge in this session."""
        issued = self.client.session.get(keys.REG_SESSION_KEY) or {}
        with (
            self.settings(**KEYS),
            mock.patch.object(
                keys, "verify_registration_response", return_value=_VerifiedRegistration
            ),
        ):
            return self.post(
                reverse("mfa:key-register"),
                {
                    "name": name,
                    "credential": credential(raw_id, challenge=issued.get("challenge") or "x" * 43),
                },
            )

    def tap(self, confirm=True, status=None):
        """A key tap through the endpoints: assertion options, then the answer.

        ``confirm`` is how a signed-in page asks for a token to confirm an
        action with; without it the same ceremony finishes a pending sign-in.
        """
        suffix = "?confirm=1" if confirm else ""
        self.post(f"{reverse('mfa:verify-key-options')}{suffix}", {}, status=200, **BROWSER)
        return self.post(
            f"{reverse('mfa:verify-key')}{suffix}",
            {
                "credential": credential(
                    ceremony="get",
                    challenge=self.challenge(keys.AUTH_SESSION_KEY),
                )
            },
            status=status,
            verify=_VerifiedAuthentication,
            **BROWSER,
        )

    def key_token(self):
        answer = self.body(self.tap())
        assert "token" in answer, answer
        return answer["token"]


class RelyingPartyTests(KeyTestCase):
    """The relying party is a setting. A host header must never decide which
    identity a key is bound to."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("wa-alice", password=STRONG, role="agent")
        enroll(self.user)
        key_fixture(self.user)
        self.request = self.client.get("/").wsgi_request
        self.client.force_login(self.user)

    def test_keys_are_unavailable_without_a_secure_public_url(self):
        with self.settings(MFA_PUBLIC_URL=""):
            self.assertEqual(keys.relying_party(self.request), ("", ""))
            self.assertIn("MFA_PUBLIC_URL", keys.unavailable_reason(""))
            page = self.client.get(reverse("mfa:security"))
            self.assertContains(page, "Set MFA_PUBLIC_URL")
            self.assertNotContains(page, 'id="mfa-key-add"')

        with self.settings(MFA_PUBLIC_URL="http://civil.example.com"):
            reason = keys.unavailable_reason(keys.relying_party(self.request)[1])
            self.assertEqual(reason, "Security keys need HTTPS.")
            self.assertContains(
                self.client.get(reverse("mfa:security")), "Security keys need HTTPS."
            )

        # Codes keep working either way.
        self.assertContains(self.client.get(reverse("mfa:security")), "Make new recovery codes")

    def test_relying_party_comes_from_settings_not_the_host_header(self):
        with self.settings(MFA_PUBLIC_URL="https://civil.example.com:8443/"):
            request = self.client.get("/", HTTP_HOST="attacker.example").wsgi_request
            self.assertEqual(keys.relying_party(request), (RP_ID, "https://civil.example.com:8443"))

        # And the options a signed-in user is handed name the configured host
        # only, however the request arrived — that is the identity a key saved
        # through it will be bound to.
        # (Jackil refuses unknown hosts outright; allow any here so the view,
        # not ALLOWED_HOSTS, is what is being tested.)
        with self.settings(**KEYS, ALLOWED_HOSTS=["*"]):
            TotpAttempt.objects.filter(user=self.user).delete()
            options = self.body(
                self.post(
                    reverse("mfa:key-options"),
                    {"code": generate_totp(SECRET)},
                    status=200,
                    HTTP_HOST="attacker.example",
                )
            )
        self.assertEqual(options["rpId"], RP_ID)
        self.assertEqual(options["origin"], PUBLIC_URL)
        self.assertNotIn("attacker.example", json.dumps(options))

    def test_localhost_http_is_a_secure_context(self):
        with self.settings(MFA_PUBLIC_URL="http://localhost:8000"):
            rp_id, origin = keys.relying_party(self.request)
            self.assertEqual(rp_id, "localhost")
            self.assertEqual(keys.unavailable_reason(origin), "")

    def test_the_relying_party_name_defaults_to_the_issuer(self):
        with self.settings(MFA_RP_NAME="", MFA_ISSUER="Civil"):
            self.assertEqual(keys.rp_name(), "Civil")
        with self.settings(MFA_RP_NAME="CivilHQ"):
            self.assertEqual(keys.rp_name(), "CivilHQ")


class AddAKeyTests(KeyTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("wa-carol", password=STRONG, role="agent")
        enroll(self.user)
        self.client.force_login(self.user)

    def ask_for_options(self, code):
        with self.settings(**KEYS):
            return self.post(reverse("mfa:key-options"), {"code": code})

    def test_register_needs_a_current_factor_and_stores_the_key(self):
        refused = self.ask_for_options("000000")
        self.assertEqual(refused.status_code, 401)
        self.assertIn("current", self.body(refused)["error"])
        self.assertFalse(SecurityKey.objects.filter(user=self.user).exists())

        # Without that confirmation the ceremony is worth nothing.
        refused = self.add_key()
        self.assertEqual(refused.status_code, 401)

        self.assertEqual(self.ask_for_options(generate_totp(SECRET)).status_code, 200)
        response = self.add_key()
        self.assertEqual(response.status_code, 201, response.content[:300])
        key = SecurityKey.objects.get(user=self.user)
        self.assertEqual(key.name, "Office key")
        self.assertEqual(bytes(key.credential_id), CRED_ID)
        self.assertEqual(bytes(key.public_key), PUBLIC_KEY)
        self.assertEqual(key.sign_count, 7)
        self.assertEqual(list(key.transports), ["usb"])
        self.assertIsNone(key.last_used_at)

    def test_registration_challenge_is_single_use(self):
        self.assertEqual(self.ask_for_options(generate_totp(SECRET)).status_code, 200)
        # Two attempts in flight: the first takes the challenge and its expiry
        # with it, so the second has nothing to be checked against. (A browser
        # is refused earlier by the duplicate credential; this pins the server.)
        good = self.add_key(name="First")
        self.assertEqual(good.status_code, 201)
        # The confirmation that entitled the first is spent with it, so a
        # second registration is refused before any challenge is looked at.
        stale = self.add_key(name="Twice")
        self.assertEqual(stale.status_code, 401)
        self.assertEqual(SecurityKey.objects.filter(user=self.user).count(), 1)

    def test_a_wrong_challenge_is_refused(self):
        """The library's own comparison is live: answering a challenge nobody
        issued does not enrol anything."""
        self.assertEqual(self.ask_for_options(generate_totp(SECRET)).status_code, 200)
        with mock.patch.object(
            keys, "verify_registration_response", return_value=_VerifiedRegistration
        ):
            response = self.post(
                reverse("mfa:key-register"),
                {"name": "Guessed", "credential": credential(challenge="x" * 43)},
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SecurityKey.objects.filter(user=self.user).exists())

    def test_an_expired_challenge_is_refused(self):
        self.assertEqual(self.ask_for_options(generate_totp(SECRET)).status_code, 200)
        with mock.patch(
            "apps.mfa.keys.time.time",
            return_value=now().timestamp() + keys.CHALLENGE_SECONDS * 4,
        ):
            response = self.add_key(name="Late")
        self.assertEqual(response.status_code, 400)

    def test_options_say_why_keys_are_off_before_any_code_is_spent(self):
        before = TotpAttempt.objects.filter(user=self.user).count()
        with self.settings(MFA_PUBLIC_URL=""):
            response = self.post(
                reverse("mfa:key-options"), {"code": generate_totp(SECRET)}, status=400
            )
        self.assertIn("MFA_PUBLIC_URL", self.body(response)["error"])
        self.assertEqual(TotpAttempt.objects.filter(user=self.user).count(), before)

    def test_a_key_is_listed_on_the_security_page(self):
        key_fixture(self.user)
        with self.settings(**KEYS):
            page = self.client.get(reverse("mfa:security"))
        self.assertContains(page, "Office key")
        self.assertContains(page, "added")

    def test_a_key_can_be_removed_with_a_current_code(self):
        key = key_fixture(self.user)
        response = self.client.post(
            reverse("mfa:key-delete", args=[key.pk]),
            json.dumps({"code": generate_totp(SECRET)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertFalse(SecurityKey.objects.filter(pk=key.pk).exists())

    def test_a_key_can_be_removed_with_a_key_tap(self):
        key_fixture(self.user)
        spare = SecurityKey.objects.create(
            user=self.user,
            name="Spare",
            credential_id=b"\x07spare",
            public_key=PUBLIC_KEY,
            sign_count=1,
            transports=[],
        )
        with self.settings(**KEYS):
            token = self.key_token()
            response = self.client.post(
                reverse("mfa:key-delete", args=[spare.pk]),
                json.dumps({"code": token}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertTrue(SecurityKey.objects.filter(name="Office key").exists())

    def test_removing_without_a_current_factor_is_refused(self):
        key = key_fixture(self.user)
        response = self.client.post(
            reverse("mfa:key-delete", args=[key.pk]),
            json.dumps({"code": "000000"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertTrue(SecurityKey.objects.filter(pk=key.pk).exists())

    def test_removing_someone_elses_key_is_not_found(self):
        other = get_user_model().objects.create_user("wa-other", password=STRONG, role="agent")
        key = key_fixture(other)
        response = self.client.post(
            reverse("mfa:key-delete", args=[key.pk]),
            json.dumps({"code": generate_totp(SECRET)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(SecurityKey.objects.filter(pk=key.pk).exists())

    def test_cannot_remove_the_last_key_without_an_authenticator(self):
        MfaProfile.objects.filter(user=self.user).delete()
        key = key_fixture(self.user)
        with self.settings(**KEYS):
            token = self.key_token()
            refused = self.client.post(
                reverse("mfa:key-delete", args=[key.pk]),
                json.dumps({"code": token}),
                content_type="application/json",
            )
        self.assertEqual(refused.status_code, 400)
        self.assertIn("authenticator app", self.body(refused)["error"])
        self.assertTrue(SecurityKey.objects.filter(pk=key.pk).exists())


class SignInWithAKeyTests(KeyTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("wa-dave", password=STRONG, role="agent")
        key_fixture(self.user)

    def password_step(self):
        return self.client.post(
            reverse("accounts:login"), {"username": "wa-dave", "password": STRONG}
        )

    def signed_in(self):
        return "_auth_user_id" in self.client.session._session

    def test_sign_in_with_a_key_finishes_the_pending_sign_in(self):
        with self.settings(**KEYS):
            resp = self.password_step()
            page = self.client.get(resp["Location"])
            self.assertContains(page, "Use a security key")

            options = self.body(
                self.post(reverse("mfa:verify-key-options"), {}, status=200, **BROWSER)
            )
            self.assertEqual(options["rpId"], RP_ID)
            self.assertEqual(len(options["allowCredentials"]), 1)
            self.assertEqual(options["allowCredentials"][0]["transports"], ["usb"])

            verified = self.body(self.tap(confirm=False))
            self.assertEqual(verified["next"], "/")
            self.assertTrue(self.signed_in())

            key = SecurityKey.objects.get(user=self.user)
            self.assertEqual(key.sign_count, 8)
            self.assertIsNotNone(key.last_used_at)
            # A key tap is not a wrong code: the counter a typed code uses is
            # left clean, so the next attempt gets its full five tries.
            self.assertFalse(TotpAttempt.objects.filter(user=self.user).exists())
            self.assertEqual(self.client.get("/").status_code, 200)

    def test_key_options_need_a_pending_sign_in(self):
        with self.settings(**KEYS):
            response = self.client.post(
                reverse("mfa:verify-key-options"),
                json.dumps({}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_the_key_button_is_offered_only_with_a_key_and_a_secure_url(self):
        self.password_step()
        self.assertNotContains(self.client.get(reverse("mfa:verify")), "Use a security key")
        with self.settings(**KEYS):
            self.assertContains(self.client.get(reverse("mfa:verify")), "Use a security key")
        SecurityKey.objects.filter(user=self.user).delete()
        with self.settings(**KEYS):
            self.assertNotContains(self.client.get(reverse("mfa:verify")), "Use a security key")

    def test_a_key_from_another_user_is_refused(self):
        stranger = get_user_model().objects.create_user(
            "wa-stranger", password=STRONG, role="agent"
        )
        stolen = key_fixture(stranger, name="theirs", raw_id=b"\x09not-mine")
        self.password_step()
        with self.settings(**KEYS):
            # The options call hands a browser only the pending user's
            # credentials; presenting somebody else's anyway is refused before
            # anything at all is verified.
            self.post(reverse("mfa:verify-key-options"), {}, status=200, **BROWSER)
            with mock.patch.object(keys, "verify_authentication_response") as verify:
                response = self.client.post(
                    reverse("mfa:verify-key"),
                    json.dumps({"credential": credential(bytes(stolen.credential_id))}),
                    content_type="application/json",
                    **BROWSER,
                )
        self.assertEqual(response.status_code, 400)
        verify.assert_not_called()
        self.assertFalse(self.signed_in())

    def test_failed_key_attempts_count_against_the_limit(self):
        self.password_step()
        with self.settings(**KEYS):
            for _ in range(5):
                self.post(reverse("mfa:verify-key-options"), {}, status=200, **BROWSER)
                response = self.client.post(
                    reverse("mfa:verify-key"),
                    json.dumps({"credential": None}),
                    content_type="application/json",
                    **BROWSER,
                )
                self.assertEqual(response.status_code, 400)
        self.assertEqual(TotpAttempt.objects.filter(user=self.user).count(), 5)

        with self.settings(**KEYS):
            locked = self.post(
                reverse("mfa:verify-key"),
                {"credential": None},
                verify=_VerifiedAuthentication,
                **BROWSER,
            )
        self.assertEqual(locked.status_code, 429)
        self.assertFalse(self.signed_in())

    def test_a_typed_key_token_does_not_finish_the_sign_in(self):
        """The key button hands the token to the endpoint; typing it into the
        six-digit field is not a way past the second factor."""
        self.client.force_login(self.user)
        with self.settings(**KEYS):
            token = self.key_token()
        self.assertTrue(token.startswith(keys.KEY_TOKEN_PREFIX))

        self.client.post(reverse("accounts:logout"))
        self.password_step()
        resp = self.client.post(reverse("mfa:verify"), {"code": token})
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "six-digit", status_code=400)
        self.assertFalse(self.signed_in())


class KeyTokenTests(KeyTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("wa-erin", password=STRONG, role="agent")

    def test_key_token_is_single_use_and_expires(self):
        from datetime import timedelta
        from types import SimpleNamespace

        from django.utils.timezone import now

        from apps.mfa.models import KeyToken

        token = keys.KEY_TOKEN_PREFIX + "a" * 43
        digest = keys._token_digest(token)
        # Stored hashed: a dump of the table must not hand over a live factor.
        self.assertNotIn(keys.KEY_TOKEN_PREFIX, digest)
        mine = SimpleNamespace(session=SimpleNamespace(session_key="browser-1"))
        theirs = SimpleNamespace(session=SimpleNamespace(session_key="browser-2"))

        self.assertFalse(keys.consume_key_token(mine, self.user, token))
        self.assertFalse(keys.consume_key_token(mine, self.user, "totp123"))
        self.assertFalse(keys.consume_key_token(mine, self.user, None))

        def issue(expires_in=60):
            KeyToken.objects.update_or_create(
                digest=digest,
                defaults={
                    "user": self.user,
                    "session_key": "browser-1",
                    "expires_at": now() + timedelta(seconds=expires_in),
                },
            )

        issue()
        self.assertTrue(keys.consume_key_token(mine, self.user, token))
        # Spent: the second use has nothing left to delete.
        self.assertFalse(keys.consume_key_token(mine, self.user, token))

        issue()
        other = get_user_model().objects.create_user("wa-zed", password=STRONG, role="agent")
        self.assertFalse(keys.consume_key_token(mine, other, token))
        # Another browser holding the token cannot spend it either.
        self.assertFalse(keys.consume_key_token(theirs, self.user, token))
        self.assertTrue(keys.consume_key_token(mine, self.user, token))

        issue(expires_in=-1)
        self.assertFalse(keys.consume_key_token(mine, self.user, token))

    def test_a_key_token_confirms_a_security_page_action(self):
        enroll(self.user)
        key_fixture(self.user)
        self.client.force_login(self.user)
        make_codes(self.user)
        with self.settings(**KEYS):
            token = self.key_token()
            self.assertGreater(RecoveryCode.objects.filter(user=self.user).count(), 0)
            response = self.client.post(reverse("mfa:security"), {"action": "codes", "code": token})
        self.assertRedirects(response, reverse("mfa:codes"))
        # A new set replaced the old one, and the token cannot be spent twice.
        self.assertEqual(RecoveryCode.objects.filter(user=self.user).count(), RECOVERY_CODE_COUNT)
        shown = self.client.session[views.FRESH_CODES_KEY]
        again = self.client.post(reverse("mfa:security"), {"action": "codes", "code": token})
        self.assertEqual(again.status_code, 200)
        # Refused: no third set was made in place of the one just shown.
        self.assertEqual(self.client.session[views.FRESH_CODES_KEY], shown)


class SecondFactorTests(TestCase):
    def test_has_second_factor_counts_keys(self):
        user = get_user_model().objects.create_user("wa-frank", password=STRONG, role="agent")
        self.assertFalse(has_second_factor(user))
        key_fixture(user)
        self.assertTrue(has_second_factor(user))

        other = get_user_model().objects.create_user("wina", password=STRONG, role="agent")
        enroll(other)
        self.assertTrue(has_second_factor(other))


class SessionHygieneTests(TestCase):
    def test_a_new_password_step_forgets_a_pending_key_gate(self):
        user = get_user_model().objects.create_user("wa-gina", password=STRONG, role="agent")
        enroll(user)
        session = self.client.session
        session[views.KEY_GATE_KEY] = str(user.pk)
        session.save()
        self.client.post(reverse("accounts:login"), {"username": "wa-gina", "password": STRONG})
        self.assertNotIn(views.KEY_GATE_KEY, self.client.session._session)


class EnrolmentStillNeedsAnAuthenticatorTests(KeyTestCase):
    """Phase 01's guard, now that a key is a factor: a pending user holding a
    key is never walked through the authenticator enrolment page."""

    def test_a_pending_user_with_a_key_goes_to_the_code_step(self):
        user = get_user_model().objects.create_user("wa-hugo", password=STRONG, role="agent")
        MfaProfile.objects.create(user=user)
        key_fixture(user)
        resp = self.client.post(
            reverse("accounts:login"), {"username": "wa-hugo", "password": STRONG}
        )
        page = self.client.get(resp["Location"])
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Verify it")
        setup = self.client.get(reverse("mfa:setup"))
        self.assertEqual(setup.status_code, 302)
        self.assertIn("/mfa/verify/", setup["Location"])

    def test_the_security_page_offers_keys_to_someone_with_only_a_key(self):
        user = get_user_model().objects.create_user("wa-ivy", password=STRONG, role="agent")
        key_fixture(user)
        self.client.force_login(user)
        with self.settings(**KEYS):
            page = self.client.get(reverse("mfa:security"))
        self.assertContains(page, "Office key")
        self.assertContains(page, 'id="mfa-key-add"')


class ModelTests(TestCase):
    def test_the_key_row_reads_as_a_key(self):
        user = get_user_model().objects.create_user("wa-kate", password=STRONG, role="agent")
        key = key_fixture(user, name="NFC tag")
        self.assertEqual(str(key), f"key 'NFC tag' <user {user.pk}>")
        self.assertEqual(list(SecurityKey.objects.filter(user=user)), [key])


class OriginPinTests(KeyTestCase):
    def test_assertion_origin_is_the_configured_one_whatever_the_origin_header_says(self):
        user = get_user_model().objects.create_user("wa-oscar", password=STRONG, role="agent")
        enroll(user)
        key_fixture(user)
        self.client.force_login(user)
        seen = {}

        def fake_verify(**kwargs):
            seen["origin"] = kwargs["expected_origin"]
            return _VerifiedAuthentication

        with self.settings(**KEYS):
            self.post(f"{reverse('mfa:verify-key-options')}?confirm=1", {}, status=200)
            with mock.patch.object(keys, "verify_authentication_response", side_effect=fake_verify):
                self.client.post(
                    f"{reverse('mfa:verify-key')}?confirm=1",
                    json.dumps(
                        {
                            "credential": credential(
                                ceremony="get", challenge=self.challenge(keys.AUTH_SESSION_KEY)
                            )
                        }
                    ),
                    content_type="application/json",
                    HTTP_ORIGIN="https://evil.example",
                )
        self.assertEqual(seen["origin"], PUBLIC_URL)

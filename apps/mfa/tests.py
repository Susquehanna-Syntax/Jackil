"""The sign-in step: a password alone gets you nowhere, a code finishes it.

Codes are made with ``apps.mfa.totp.generate_totp`` — no time freezing: a code
generated now verifies now. The sign-in POSTs to ``/login/`` go through the
real view chain, so the second factor cannot be short-circuited by whatever
the app happens to be rendering at the URL it started from.
"""

from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now

from apps.mfa import views
from apps.mfa.models import MfaProfile, RecoveryCode
from apps.mfa.recovery import RECOVERY_CODE_COUNT, make_codes
from apps.mfa.totp import generate_totp

STRONG = "correct-horse-battery-9"
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def enroll(user, secret=SECRET):
    """Install a confirmed authenticator without going through the QR page."""
    profile, _ = MfaProfile.objects.get_or_create(user=user)
    profile.totp_secret = secret
    profile.totp_confirmed_at = now()
    profile.save()
    return secret


class SignInStepTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("alice", password=STRONG, role="agent")

    def password_step(self, next_url=None):
        """The first step, and only the first step."""
        data = {"username": "alice", "password": STRONG}
        if next_url:
            data["next"] = next_url
        return self.client.post(reverse("accounts:login"), data)

    def second_step(self, code):
        return self.client.post(reverse("mfa:verify"), {"code": code})

    def signed_in(self):
        return "_auth_user_id" in self.client.session._session

    def test_password_alone_does_not_sign_in(self):
        enroll(self.user)
        resp = self.password_step()
        self.assertRedirects(resp, reverse("mfa:verify"), fetch_redirect_response=False)
        self.assertFalse(self.signed_in())

        home = self.client.get("/tickets/")
        self.assertEqual(home.status_code, 302)
        self.assertIn("/login/", home["Location"])
        people = self.client.get(reverse("console:settings_home"))
        self.assertIn(people.status_code, (302, 403))

    def test_first_sign_in_enrols_then_shows_codes_then_signs_in(self):
        resp = self.password_step()
        # No factor yet: the second step leads to the QR and the key to type in.
        page = self.client.get(resp["Location"])
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Scan this with your authenticator app")
        self.assertFalse(self.signed_in())
        secret = self.client.session[views.ENROL_KEY]

        resp = self.client.post(reverse("mfa:setup"), {"code": generate_totp(secret)})
        # Enrolment is confirmed by the same code that finishes the sign-in —
        # recovery codes are handed out *after* it, so they cannot open a door.
        self.assertRedirects(resp, reverse("mfa:codes"))
        self.assertTrue(self.signed_in())
        shown = self.client.session[views.FRESH_CODES_KEY]
        self.assertEqual(len(shown), RECOVERY_CODE_COUNT)
        self.assertContains(
            self.client.get(reverse("mfa:codes")), "this is the only time they are shown"
        )

        # The codes page hands back the destination the password step was asked
        # for, and the codes leave the session either way.
        resp = self.client.post(reverse("mfa:codes"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/")
        self.assertNotIn(views.FRESH_CODES_KEY, self.client.session._session)

        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(
            RecoveryCode.objects.filter(user=self.user, used_at__isnull=True).count(),
            RECOVERY_CODE_COUNT,
        )

    def test_wrong_code_keeps_you_out_and_six_wrong_codes_lock_for_now(self):
        enroll(self.user)
        self.password_step()
        # Five wrong codes are answered as wrong; the sixth is refused before
        # its code is even looked at, so a live code no longer gets you in.
        for _ in range(5):
            resp = self.second_step("000000")
            self.assertEqual(resp.status_code, 400)
            self.assertFalse(self.signed_in())

        resp = self.second_step(generate_totp(SECRET))
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Too many wrong codes", status_code=400)
        self.assertFalse(self.signed_in())

    def test_code_cannot_be_replayed(self):
        enroll(self.user)
        code = generate_totp(SECRET)
        self.password_step()
        resp = self.second_step(code)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.signed_in())

        self.client.post(reverse("accounts:logout"))
        self.password_step()
        resp = self.second_step(code)
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "already used", status_code=400)
        self.assertFalse(self.signed_in())

    def test_recovery_code_signs_in_once(self):
        enroll(self.user)
        plain = make_codes(self.user)[0]
        self.password_step()
        resp = self.second_step(plain.upper().replace("-", ""))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/")

        # Same code a second time — the dash and capitals were typed differently,
        # but it was the same code and it is spent.
        self.client.post(reverse("accounts:logout"))
        self.password_step()
        resp = self.second_step(plain)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(self.signed_in())
        self.assertEqual(
            RecoveryCode.objects.filter(user=self.user, used_at__isnull=False).count(), 1
        )

    def test_pending_sign_in_expires(self):
        enroll(self.user)
        with mock.patch("time.time", return_value=1_700_000_000.0):
            self.password_step()
        with mock.patch("time.time", return_value=1_700_000_000.0 + 301):
            resp = self.second_step(generate_totp(SECRET))
        self.assertRedirects(resp, reverse("accounts:login"))
        self.assertFalse(self.signed_in())

    def test_next_is_kept_but_only_on_this_host(self):
        enroll(self.user)
        self.password_step(next_url="https://evil.example/")
        resp = self.second_step(generate_totp(SECRET))
        self.assertEqual(resp["Location"], "/")

    def test_next_lands_on_the_page_it_named_when_it_is_relative(self):
        enroll(self.user)
        self.password_step(next_url="/tickets/")
        resp = self.second_step(generate_totp(SECRET))
        self.assertEqual(resp["Location"], "/tickets/")

    def test_admin_login_goes_through_the_two_step_sign_in(self):
        get_user_model().objects.filter(pk=self.user.pk).update(is_staff=True)
        resp = self.client.get("/admin/login/", {"next": "/admin/auth/user/"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])
        self.assertIn("next", resp["Location"])

    def test_signed_in_staff_still_reach_the_admin(self):
        get_user_model().objects.filter(pk=self.user.pk).update(is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)


class EncryptedAtRestTests(TestCase):
    def test_secret_is_encrypted_at_rest(self):
        from django.db import connection

        user = get_user_model().objects.create_user("bob", password=STRONG, role="agent")
        enroll(user)
        column = MfaProfile._meta.get_field("totp_secret_encrypted").column
        with connection.cursor() as cur:
            cur.execute(f"select {column} from mfa_mfaprofile")
            raw = bytes(cur.fetchone()[0])
        self.assertNotIn(SECRET.encode(), raw)
        self.assertEqual(MfaProfile.objects.get(user=user).totp_secret, SECRET)


class SecurityPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("carol", password=STRONG, role="agent")
        enroll(self.user)
        make_codes(self.user)
        self.client.force_login(self.user)

    def act(self, action, code):
        return self.client.post(reverse("mfa:security"), {"action": action, "code": code})

    def test_new_recovery_codes_need_a_current_code(self):
        before = RecoveryCode.objects.filter(user=self.user).count()
        resp = self.act("codes", "000000")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(views.FRESH_CODES_KEY, self.client.session._session)
        self.assertEqual(RecoveryCode.objects.filter(user=self.user).count(), before)

    def test_a_recovery_code_also_confirms_a_new_set(self):
        resp = self.act("codes", make_codes(self.user)[0])
        self.assertRedirects(resp, reverse("mfa:codes"))

    def test_a_fresh_set_replaces_the_old_one(self):
        resp = self.act("codes", generate_totp(SECRET))
        self.assertRedirects(resp, reverse("mfa:codes"))
        self.assertEqual(len(self.client.session[views.FRESH_CODES_KEY]), RECOVERY_CODE_COUNT)
        # The codes the user held are replaced, not added to.
        self.assertEqual(RecoveryCode.objects.filter(user=self.user).count(), RECOVERY_CODE_COUNT)

    def test_there_is_no_self_service_reset(self):
        """Someone holding only a session must not be able to clear the
        factors and enrol their own: resets are a staff action."""
        resp = self.client.post(reverse("mfa:security"), {"action": "reset"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(MfaProfile.objects.get(user=self.user).totp_secret, SECRET)
        self.assertTrue(get_user_model().objects.get(pk=self.user.pk).is_active)

    def test_new_authenticator_keeps_the_old_until_confirmed(self):
        resp = self.act("setup", "000000")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(views.ENROL_KEY, self.client.session._session)
        self.assertEqual(MfaProfile.objects.get(user=self.user).totp_secret, SECRET)

        resp = self.act("setup", generate_totp(SECRET))
        self.assertRedirects(resp, reverse("mfa:setup"))
        new_secret = self.client.session[views.ENROL_KEY]
        self.assertNotEqual(new_secret, SECRET)

        # A wrong code on the setup page leaves the old authenticator working.
        resp = self.client.post(reverse("mfa:setup"), {"code": "000000"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(MfaProfile.objects.get(user=self.user).totp_secret, SECRET)

        resp = self.client.post(reverse("mfa:setup"), {"code": generate_totp(new_secret)})
        self.assertRedirects(resp, reverse("mfa:codes"))
        self.assertEqual(MfaProfile.objects.get(user=self.user).totp_secret, new_secret)


class SetSecretCommandTests(TestCase):
    def test_set_secret_command_refuses_without_debug(self):
        get_user_model().objects.create_user("dave", password=STRONG, role="agent")
        with self.settings(DEBUG=False), self.assertRaises(CommandError):
            call_command("mfa_set_secret", "dave", SECRET, stdout=StringIO())
        self.assertFalse(MfaProfile.objects.exists())

        with self.settings(DEBUG=True):
            call_command("mfa_set_secret", "dave", SECRET, stdout=StringIO())
        self.assertTrue(MfaProfile.objects.get(user__username="dave").confirmed())


class RecoveryCodeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("erin", password=STRONG, role="agent")

    def test_codes_are_ten_shown_as_five_dash_five_and_work_once(self):
        from apps.mfa.recovery import remaining, use_code

        codes = make_codes(self.user)
        self.assertEqual(len(codes), RECOVERY_CODE_COUNT)
        self.assertTrue(all(len(c) == 11 and c[5] == "-" for c in codes))
        self.assertEqual(remaining(self.user), RECOVERY_CODE_COUNT)

        self.assertTrue(use_code(self.user, codes[0].upper()))
        self.assertEqual(remaining(self.user), RECOVERY_CODE_COUNT - 1)
        self.assertFalse(use_code(self.user, codes[0]))

    def test_a_new_set_replaces_the_old_ones(self):
        from apps.mfa.recovery import use_code

        first = make_codes(self.user)[0]
        second = make_codes(self.user)[0]
        self.assertNotEqual(first, second)
        self.assertFalse(use_code(self.user, first))
        self.assertTrue(use_code(self.user, second))


class BypassRegressionTests(TestCase):
    """The setup and codes pages must never stand in for the second factor."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("dave", password=STRONG, role="agent")
        enroll(self.user)

    def signed_in(self):
        return "_auth_user_id" in self.client.session._session

    def test_password_alone_cannot_enrol_a_new_authenticator(self):
        """The critical one: a pending user with a factor goes to setup, gets a
        fresh secret, confirms it with their own app, and is signed in."""
        self.client.post(reverse("accounts:login"), {"username": "dave", "password": STRONG})
        resp = self.client.get(reverse("mfa:setup"))
        self.assertRedirects(resp, reverse("mfa:verify"), fetch_redirect_response=False)
        self.assertNotIn(views.ENROL_KEY, self.client.session._session)
        resp = self.client.post(reverse("mfa:setup"), {"code": "123456"})
        self.assertFalse(self.signed_in())
        self.assertEqual(MfaProfile.objects.get(user=self.user).totp_secret, SECRET)

    def test_signed_in_user_cannot_replace_the_authenticator_without_a_code(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("mfa:setup"))
        self.assertRedirects(resp, reverse("mfa:security"), fetch_redirect_response=False)
        self.assertNotIn(views.ENROL_KEY, self.client.session._session)

    def test_codes_page_never_signs_anyone_in(self):
        self.client.post(reverse("accounts:login"), {"username": "dave", "password": STRONG})
        session = self.client.session
        session[views.FRESH_CODES_KEY] = ["aaaaa-bbbbb"]
        session[views.OWNER_KEY] = str(self.user.pk)
        session.save()
        resp = self.client.post(reverse("mfa:codes"))
        self.assertFalse(self.signed_in())
        self.assertNotEqual(resp.status_code, 200)

    def test_a_new_password_step_forgets_old_codes_and_secrets(self):
        session = self.client.session
        session[views.FRESH_CODES_KEY] = ["aaaaa-bbbbb"]
        session[views.ENROL_KEY] = "JBSWY3DPEHPK3PXP"
        session.save()
        self.client.post(reverse("accounts:login"), {"username": "dave", "password": STRONG})
        for key in (views.FRESH_CODES_KEY, views.ENROL_KEY, views.OWNER_KEY):
            self.assertNotIn(key, self.client.session._session)


class RaceTests(TestCase):
    """A code or a recovery code is spent by one conditional UPDATE, so a
    second request that read the same state a moment earlier loses."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("erin", password=STRONG, role="agent")
        enroll(self.user)

    def test_a_code_spent_by_a_racing_request_is_refused(self):
        from django.utils.timezone import now

        from apps.mfa.totp import consume_totp

        user = get_user_model().objects.get(pk=self.user.pk)
        user.mfa  # this request has already read the profile
        code = generate_totp(SECRET)
        MfaProfile.objects.filter(user=user).update(last_totp_code=code, last_totp_used_at=now())
        ok, err = consume_totp(user, code)
        self.assertFalse(ok)
        self.assertIn("already used", err)

    def test_a_recovery_code_spent_by_a_racing_request_is_refused(self):
        from unittest import mock

        from django.utils.timezone import now

        from apps.mfa import recovery

        code = make_codes(self.user)[0]
        real_check = recovery.check_password

        def check_then_lose_the_race(typed, hashed):
            matched = real_check(typed, hashed)
            if matched:
                RecoveryCode.objects.filter(user=self.user).update(used_at=now())
            return matched

        with mock.patch.object(recovery, "check_password", side_effect=check_then_lose_the_race):
            self.assertFalse(recovery.use_code(self.user, code))

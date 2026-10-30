"""Jackil's wiring of apps.mfa: staff need a second factor, customers do not,
and Civil sign-ins are trusted as already two-factor."""

import uuid

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.civilsso.models import CachedCivilKey
from apps.civilsso.tests import PUBLIC_PEM, forge
from apps.mfa.models import MfaProfile
from apps.mfa.tests import SECRET, enroll
from apps.mfa.totp import generate_totp

STRONG = "correct-horse-battery-9"


def make(username, role, **extra):
    return get_user_model().objects.create_user(username, password=STRONG, role=role, **extra)


class SignInTests(TestCase):
    def _sign_in(self, username, url=None):
        return self.client.post(
            url or reverse("accounts:login"), {"username": username, "password": STRONG}
        )

    def test_customer_signs_in_with_a_password_alone(self):
        user = make("cust", "customer")
        resp = self._sign_in("cust")
        self.assertRedirects(resp, reverse("tickets:dashboard"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_agent_password_alone_does_not_sign_in(self):
        make("agent", "agent")
        resp = self._sign_in("agent")
        self.assertRedirects(resp, reverse("mfa:verify"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        resp = self.client.get(reverse("tickets:ticket_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("accounts:login")))

    def test_admin_login_goes_through_the_two_step_sign_in(self):
        user = make("boss", "admin", is_staff=True, is_superuser=True)
        enroll(user)
        resp = self.client.get("/admin/login/?next=/admin/")
        login = reverse("accounts:login")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(login))

        resp = self._sign_in("boss", url=f"{login}?next=/admin/")
        self.assertRedirects(resp, reverse("mfa:verify"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

        resp = self.client.post(reverse("mfa:verify"), {"code": generate_totp(SECRET)})
        self.assertRedirects(resp, "/admin/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/admin/").status_code, 200)


@override_settings(CIVIL_URL="http://civil.test", CIVIL_APP_SLUG="jackil")
class CivilSignInTests(TestCase):
    def test_civil_sign_in_is_not_asked_for_a_code(self):
        CachedCivilKey.store(PUBLIC_PEM, "http://civil.test/api/v1/pubkey/")
        session = self.client.session
        session["civilsso_state"] = "st4te"
        session.save()
        resp = self.client.get(
            "/accounts/civil/callback",
            {"token": forge(sub=str(uuid.uuid4())), "state": "st4te"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertNotEqual(resp["Location"], reverse("mfa:verify"))
        self.assertIn("_auth_user_id", self.client.session)


class ProfileTests(TestCase):
    def test_profile_shows_two_factor_status_for_staff_only(self):
        self.client.force_login(make("cust", "customer"))
        self.assertNotContains(self.client.get(reverse("accounts:profile")), "Two-factor sign-in")

        agent = make("agent", "agent")
        self.client.force_login(agent)
        resp = self.client.get(reverse("accounts:profile"))
        self.assertContains(resp, reverse("mfa:security"))
        self.assertContains(resp, "set it up before your next sign-in")

        enroll(agent)
        resp = self.client.get(reverse("accounts:profile"))
        self.assertContains(resp, "set up for your account")


class AdminResetTests(TestCase):
    def _reset(self, actor, target):
        self.client.force_login(actor)
        return self.client.post(
            reverse("admin:accounts_user_changelist"),
            {"action": "reset_mfa", "_selected_action": [str(target.pk)]},
            follow=True,
        )

    def test_admin_action_resets_factors_admins_only(self):
        target = make("agent", "agent")
        enroll(target)

        # Staff with admin-site access but the agent role cannot reset.
        clerk = make("clerk", "agent", is_staff=True, is_superuser=True)
        clerk.is_superuser = False
        clerk.save()
        clerk.user_permissions.add(*_user_perms())
        self._reset(clerk, target)
        self.assertTrue(MfaProfile.objects.get(user=target).totp_confirmed_at)

        boss = make("boss", "admin", is_staff=True, is_superuser=True)
        enroll(boss)
        resp = self._reset(boss, target)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            MfaProfile.objects.filter(user=target, totp_confirmed_at__isnull=False).exists()
        )
        self.assertTrue(
            LogEntry.objects.filter(
                object_id=str(target.pk), change_message="Two-factor sign-in reset."
            ).exists()
        )

        # Selecting yourself never resets your own factors.
        self._reset(boss, boss)
        self.assertTrue(MfaProfile.objects.get(user=boss).totp_confirmed_at)


def _user_perms():
    from django.contrib.auth.models import Permission

    return Permission.objects.filter(content_type__app_label="accounts", codename__endswith="_user")

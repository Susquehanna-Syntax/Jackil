"""SAML sign-in: the gates, the flow, and provisioning.

Hermetic — no IdP anywhere; OneLogin_Saml2_Auth is a fake whose methods
return what each test needs. The metadata test uses the real settings
builder because it produces our own XML offline."""

from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.saml import service, views
from apps.saml.models import SamlConfig, SamlIdentity

# OneLogin's settings validator rejects a single-label host, so the tests use
# "localhost" — the same host the accounts tests use.
HOST = "http://localhost"


def business_on():
    patcher = mock.patch("apps.licensing.service.has_feature", side_effect=lambda slug: True)
    patcher.start()
    return patcher


def configure(**overrides):
    cfg = SamlConfig.get_solo()
    cfg.enabled = True
    cfg.idp_entity_id = "https://idp.example.com/"
    cfg.idp_sso_url = "https://idp.example.com/sso"
    cfg.idp_x509_cert = (
        "-----BEGIN CERTIFICATE-----\nMIICertificateBODY\nwith newlines\n-----END CERTIFICATE-----"
    )
    for field, value in overrides.items():
        setattr(cfg, field, value)
    cfg.save()
    return cfg


class SamlTestCase(TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(reset_fake_auth)
        # OneLogin's settings validator rejects a single-label host such as
        # "testserver", so the tests run against "localhost" like accounts'.
        self.client = Client(SERVER_NAME="localhost")


class FakeAuth:
    """The one IdP an SSO test is allowed to talk to."""

    url = "https://idp.example.com/sso?SAMLRequest=abc"
    errors: list[str] = []
    reason = ""
    authenticated = True
    name_id = "alice@example.com"
    attributes: dict[str, list[str]] = {}

    def __init__(self, request_data, settings):
        self.request_data = request_data
        self.settings = settings

    request_id = "ONELOGIN_test-request"
    seen_request_id = None

    def login(self, return_to=None):
        self.return_to = return_to
        FakeAuth.last_return_to = return_to
        return self.url

    def get_last_request_id(self):
        return self.request_id

    def process_response(self, request_id=None):
        FakeAuth.seen_request_id = request_id

    def get_errors(self):
        return list(self.errors)

    def get_last_error_reason(self):
        return self.reason

    def is_authenticated(self):
        return self.authenticated

    def get_nameid(self):
        return self.name_id

    def get_attributes(self):
        return dict(self.attributes)


def reset_fake_auth():
    FakeAuth.errors = []
    FakeAuth.reason = ""
    FakeAuth.authenticated = True
    FakeAuth.name_id = "alice@example.com"
    FakeAuth.attributes = {}


class SamlRouteTests(SamlTestCase):
    def test_saml_routes_404_without_business_or_config(self):
        configure()  # config is ready; the licence decides
        for url in ("saml-login", "saml-metadata"):
            self.assertEqual(self.client.get(reverse(url)).status_code, 404)
        self.assertEqual(self.client.post(reverse("saml-acs"), {}).status_code, 404)

        business_on()
        SamlConfig.objects.filter(pk=1).update(enabled=False)
        self.assertFalse(service.active())
        for url in ("saml-login", "saml-metadata"):
            self.assertEqual(self.client.get(reverse(url)).status_code, 404)
        self.assertEqual(self.client.post(reverse("saml-acs"), {}).status_code, 404)


class LoginStartTests(SamlTestCase):
    def setUp(self):
        super().setUp()
        business_on()
        configure()
        mock.patch("apps.saml.views.OneLogin_Saml2_Auth", FakeAuth).start()

    def _session_next(self, response):
        # The request's own session: the client cookie jar still carries the
        # store from before this view ran.
        return views._NEXT_SESSION_KEY in response.wsgi_request.session

    def test_login_redirects_to_the_idp_and_keeps_a_safe_next_only(self):
        first = self.client.get(reverse("saml-login"), {"next": "/tickets/7/"})
        self.assertRedirects(first, FakeAuth.url, fetch_redirect_response=False)
        self.assertTrue(self._session_next(first))

        fresh = Client(SERVER_NAME="localhost")
        evil = fresh.get(reverse("saml-login"), {"next": "https://evil.example/x"})
        self.assertRedirects(evil, FakeAuth.url, fetch_redirect_response=False)
        self.assertFalse(self._session_next(evil))
        # Nor is the unsafe address handed to the IdP as the RelayState.
        self.assertIsNone(FakeAuth.last_return_to)


class AcsTests(SamlTestCase):
    def setUp(self):
        super().setUp()
        business_on()
        configure()
        mock.patch("apps.saml.views.OneLogin_Saml2_Auth", FakeAuth).start()
        # Every ACS test answers a sign-in this browser started.
        session = self.client.session
        session[views._REQUEST_SESSION_KEY] = FakeAuth.request_id
        session.save()

    def test_acs_refuses_an_unsolicited_or_replayed_response(self):
        alice = User.objects.create_user("alice")
        SamlIdentity.objects.create(user=alice, name_id="alice@example.com")
        self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})  # uses up the request id
        self.client.logout()
        replay = self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})
        self.assertRedirects(replay, "/login/?saml=failed", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_acs_checks_the_response_against_the_request_id(self):
        alice = User.objects.create_user("alice")
        SamlIdentity.objects.create(user=alice, name_id="alice@example.com")
        self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})
        self.assertEqual(FakeAuth.seen_request_id, FakeAuth.request_id)

    def test_acs_signs_in_a_known_identity(self):
        alice = User.objects.create_user("alice")
        SamlIdentity.objects.create(user=alice, name_id="alice@example.com")

        response = self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), alice.pk)
        self.assertEqual(SamlIdentity.objects.count(), 1)

    def test_acs_signs_in_and_honours_a_remembered_next(self):
        alice = User.objects.create_user("alice")
        SamlIdentity.objects.create(user=alice, name_id="alice@example.com")
        session = self.client.session
        session[views._NEXT_SESSION_KEY] = "/tickets/7/"
        session.save()

        response = self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})
        self.assertRedirects(response, "/tickets/7/", fetch_redirect_response=False)

    def test_acs_provisions_a_new_user_with_the_configured_role(self):
        SamlConfig.objects.filter(pk=1).update(new_user_role="agent")
        FakeAuth.attributes = {"email": ["bob@example.com"], "name": ["Bob Anthony Jones"]}

        response = self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

        bob = User.objects.get(username="bob")
        self.assertEqual(bob.role, "agent")
        self.assertEqual(bob.email, "bob@example.com")
        self.assertEqual(bob.first_name, "Bob")
        self.assertEqual(bob.last_name, "Anthony Jones")
        self.assertFalse(bob.has_usable_password())
        self.assertEqual(SamlIdentity.objects.get(name_id="alice@example.com").user, bob)

    def test_acs_never_claims_an_existing_local_username(self):
        alice = User.objects.create_user("alice", email="alice@local.example", password="pw")
        FakeAuth.attributes = {"email": ["alice@example.com"]}

        response = self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

        saml_user = User.objects.get(username="alice-2")
        self.assertEqual(saml_user.email, "alice@example.com")
        alice.refresh_from_db()
        self.assertEqual(alice.email, "alice@local.example")
        self.assertTrue(alice.has_usable_password())
        self.assertNotEqual(int(self.client.session["_auth_user_id"]), alice.pk)

    def test_acs_refuses_new_users_when_not_allowed(self):
        SamlConfig.objects.filter(pk=1).update(allow_new_users=False)

        response = self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})
        self.assertRedirects(response, "/login/?saml=failed", fetch_redirect_response=False)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(SamlIdentity.objects.count(), 0)

    def test_acs_errors_and_inactive_users_fail_to_the_login_page(self):
        FakeAuth.errors = ["invalid_response"]
        FakeAuth.reason = "Signature validation failed"
        response = self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})
        self.assertRedirects(response, "/login/?saml=failed", fetch_redirect_response=False)

        FakeAuth.errors = []
        FakeAuth.authenticated = False
        response = self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})
        self.assertRedirects(response, "/login/?saml=failed", fetch_redirect_response=False)

        FakeAuth.authenticated = True
        frozen = User.objects.create_user("frozen", password="pw")
        frozen.is_active = False
        frozen.save()
        SamlIdentity.objects.create(user=frozen, name_id="alice@example.com")
        response = self.client.post(reverse("saml-acs"), {"SAMLResponse": "x"})
        self.assertRedirects(response, "/login/?saml=failed", fetch_redirect_response=False)


class MetadataTests(SamlTestCase):
    def setUp(self):
        super().setUp()
        business_on()
        configure()

    def test_metadata_is_valid_sp_metadata(self):
        response = self.client.get(reverse("saml-metadata"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/samlmetadata+xml")
        body = response.content.decode()
        self.assertIn(f'entityID="{HOST}/saml/metadata/"', body)
        self.assertIn(f'Location="{HOST}/saml/acs/"', body)


class SettingsPageTests(SamlTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user("boss", password="pw", role="admin")
        self.agent = User.objects.create_user("helper", password="pw", role="agent")

    def test_settings_page_is_business_only_and_admin_only(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("console:saml_settings"))
        self.assertEqual(response.status_code, 402)
        self.assertIn(b"part of SQSY Business", response.content)

        business_on()
        denied = self.client.get(reverse("console:saml_settings"), follow=True)
        self.assertRedirects(denied, reverse("tickets:dashboard"))

        self.client.force_login(self.admin)
        configure()
        page = self.client.get(reverse("console:saml_settings"))
        self.assertEqual(page.status_code, 200)
        body = " ".join(page.content.decode().split())
        self.assertIn(f"{HOST}/saml/acs/", body)
        self.assertIn(f"{HOST}/saml/metadata/", body)
        self.assertIn('class="settings-nav-item tc-coral', body)


class LoginPageTests(SamlTestCase):
    def test_login_page_shows_sso_only_when_active(self):
        page = self.client.get(reverse("accounts:login"))
        self.assertNotContains(page, "Sign in with SSO")

        business_on()
        configure()
        page = self.client.get(reverse("accounts:login"), {"next": "/tickets/"})
        self.assertContains(page, "Sign in with SSO")
        body = page.content.decode()
        self.assertIn(f'href="{reverse("saml-login")}?next=/tickets/"', body)

        SamlConfig.objects.filter(pk=1).update(enabled=False)
        self.assertNotContains(self.client.get(reverse("accounts:login")), "Sign in with SSO")

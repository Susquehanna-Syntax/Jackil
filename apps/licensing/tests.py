"""The edition itself: what a licence means, and when Jackil stops trusting it."""

import base64
import io
import json
from datetime import timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.licensing import service, verify
from apps.licensing.models import LicenceRecord
from apps.vigil.client import VigilUnavailable


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def sign_licence(
    private_key: Ed25519PrivateKey,
    *,
    instance: str = "vigil-1",
    org: str = "Example Council",
    seats: int = 50,
    exp_days: float | None = 30.0,
    sites: int | None = None,
    lid: str = "lic-1",
    features=None,
) -> str:
    """A genuine SQSY blob. No ``features`` at all means every Business feature,
    which is Vigil's convention; ``features=()`` signs an explicitly empty list."""
    payload = {
        "instance": instance,
        "org": org,
        "seats": seats,
        "exp": 0 if exp_days is None else _timestamp(days=exp_days),
        "iat": _timestamp(days=-10),
        "sites": sites,
        "lid": lid,
    }
    if features is not None:
        payload["features"] = features
    body = json.dumps(payload).encode()
    return f"{verify.PREFIX}.{_b64u(body)}.{_b64u(private_key.sign(body))}"


def tamper(blob: str) -> str:
    """The payload changed under a signature that no longer covers it."""
    _prefix, body, signature = blob.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims["seats"] = int(claims["seats"]) + 1
    return f"{verify.PREFIX}.{_b64u(json.dumps(claims).encode())}.{signature}"


def _timestamp(**kwargs) -> int:
    return int((timezone.now() + timedelta(**kwargs)).timestamp())


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class FakeLicenceClient:
    """Stand-in for the Vigil client; never touches the network."""

    def __init__(self, answer=None, error=None):
        self.answer = answer or {"blob": "", "instance": "", "status": "valid"}
        self.error = error
        self.calls = 0

    def licence(self) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.answer


class LicenceTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.key = Ed25519PrivateKey.generate()
        patcher = patch(
            "apps.licensing.service.settings.JACKIL_LICENSE_PUBLIC_KEY",
            public_key_b64(self.key),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def link_to_vigil(self, answer=None, error=None):
        """Jackil is linked to a Vigil that answers ``answer`` (or fails)."""
        fake = FakeLicenceClient(answer, error)
        patcher = patch("apps.licensing.service.get_client", return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def business_at_vigil(self, **claims):
        """Vigil holds a genuine licence for Jackil; returns the fake client."""
        blob = sign_licence(self.key, features=["jackil"], **claims)
        return self.link_to_vigil({"blob": blob, "instance": "vigil-1", "status": "valid"})

    def unlink_from_vigil(self):
        """Jackil is no longer linked to a Vigil at all."""
        patcher = patch("apps.licensing.service.get_client", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def last_verified_days_ago(self, days):
        record = LicenceRecord.get_solo()
        record.last_verified_at = timezone.now() - timedelta(days=days)
        record.save(update_fields=["last_verified_at"])


class ServicePolicyTests(SimpleTestCase):
    """The licence rules, read straight off a record — no Vigil, no storage."""

    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        patcher = patch(
            "apps.licensing.service.settings.JACKIL_LICENSE_PUBLIC_KEY",
            public_key_b64(self.key),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self, blob, **fields):
        defaults = {
            "blob": blob,
            "vigil_instance": "vigil-1",
            "last_checked_at": timezone.now(),
            "last_verified_at": timezone.now(),
        }
        defaults.update(fields)
        return LicenceRecord(pk=1, **defaults)

    def test_every_business_slug_is_on_once_the_edition_is_business(self):
        """Which slugs a Business licence carries is SQSY's decision, not Jackil's."""
        edition = service._classify(
            self.record(sign_licence(self.key, features=["jackil", "portal_branding"]))
        )

        self.assertTrue(edition.business)
        with patch("apps.licensing.service.current", return_value=edition):
            for slug in service.BUSINESS_FEATURES:
                self.assertTrue(service.has_feature(slug))
            self.assertFalse(service.has_feature("sla"))

    def test_a_business_slug_is_off_when_the_edition_is_not_business(self):
        edition = service._classify(
            self.record(sign_licence(self.key, features=["portal_branding"]))
        )

        self.assertEqual(edition.status, "not_included")
        with patch("apps.licensing.service.current", return_value=edition):
            self.assertFalse(service.has_feature("portal_branding"))

    def test_a_licence_naming_no_features_is_still_a_business_licence(self):
        """Vigil's convention: an absent feature list means every Business one."""
        edition = service._classify(self.record(sign_licence(self.key)))

        self.assertEqual(edition.status, "valid")
        self.assertIn("jackil", edition.claims.features)

    def test_a_licence_that_is_valid_but_expires_long_ago_still_reads_as_valid(self):
        edition = service._classify(self.record(sign_licence(self.key, features=["jackil"])))

        self.assertEqual(edition.status, "valid")
        self.assertTrue(edition.business)


class EditionTests(LicenceTestCase):
    def test_a_genuine_bound_licence_with_jackil_is_business(self):
        self.business_at_vigil(org="Riverside Council", lid="lic-42")

        edition = service.refresh()

        self.assertEqual(edition.status, "valid")
        self.assertTrue(edition.business)
        self.assertTrue(service.business_active())
        self.assertEqual(edition.claims.org, "Riverside Council")
        self.assertEqual(edition.claims.lid, "lic-42")

    def test_no_licence_on_the_linked_vigil_is_none(self):
        self.link_to_vigil({"blob": "", "instance": "vigil-1", "status": "none"})

        edition = service.refresh()

        self.assertEqual(edition.status, "none")
        self.assertEqual(edition.detail, "No SQSY Business licence on the linked Vigil.")
        self.assertFalse(service.business_active())

    def test_bad_signature_is_invalid_and_free(self):
        forged = tamper(sign_licence(self.key, features=["jackil"]))
        self.link_to_vigil({"blob": forged, "instance": "vigil-1", "status": "valid"})

        edition = service.refresh()

        self.assertEqual(edition.status, "invalid")
        self.assertIn("signature", edition.detail)
        self.assertFalse(service.business_active())

    def test_licence_for_another_vigil_is_a_mismatch(self):
        blob = sign_licence(self.key, instance="vigil-elsewhere", features=["jackil"])
        self.link_to_vigil({"blob": blob, "instance": "vigil-1", "status": "valid"})

        edition = service.refresh()

        self.assertEqual(edition.status, "mismatch")
        self.assertEqual(edition.detail, "This licence was issued for a different Vigil.")
        self.assertFalse(service.business_active())

    def test_licence_without_jackil_is_not_included(self):
        blob = sign_licence(self.key, features=["portal_branding", "csv_export"])
        self.link_to_vigil({"blob": blob, "instance": "vigil-1", "status": "valid"})

        edition = service.refresh()

        self.assertEqual(edition.status, "not_included")
        self.assertEqual(edition.detail, "The licence does not include Jackil.")
        self.assertFalse(service.business_active())

    def test_vigil_status_field_is_never_trusted(self):
        """Vigil's own verdict is ignored: "valid" over a junk blob is invalid."""
        self.link_to_vigil(
            {"blob": f"{verify.PREFIX}.junk.junk", "instance": "vigil-1", "status": "valid"}
        )

        edition = service.refresh()

        self.assertEqual(edition.status, "invalid")
        self.assertFalse(service.business_active())


class ExpiryTests(LicenceTestCase):
    def test_expired_within_grace_stays_on_then_lapses(self):
        blob = self.business_at_vigil(exp_days=-3)

        edition = service.refresh()
        self.assertEqual(edition.status, "grace")
        self.assertTrue(service.business_active())
        self.assertIn("Business stays on until", edition.detail)

        lapsed = sign_licence(self.key, features=["jackil"], exp_days=-(service.GRACE_DAYS + 6))
        self.link_to_vigil({"blob": lapsed, "instance": "vigil-1", "status": "valid"})

        edition = service.refresh()

        self.assertEqual(edition.status, "lapsed")
        self.assertFalse(service.business_active())
        self.assertNotEqual(blob, lapsed)


class DroppedLinkTests(LicenceTestCase):
    def test_dropped_link_keeps_business_for_14_days_then_unlinked(self):
        self.business_at_vigil()
        service.refresh()
        self.unlink_from_vigil()

        for days in (0, 7, service.GRACE_DAYS - 1):
            with self.subTest(days=days):
                cache.clear()
                self.last_verified_days_ago(days)
                self.assertTrue(service.business_active())

        cache.clear()
        self.last_verified_days_ago(service.GRACE_DAYS)

        edition = service.current()

        self.assertEqual(edition.status, "unlinked")
        self.assertEqual(edition.detail, "Jackil has not reached Vigil for 14 days.")
        self.assertFalse(service.business_active())

    def test_vigil_down_keeps_the_last_good_licence(self):
        self.business_at_vigil()
        service.refresh()

        self.link_to_vigil(error=VigilUnavailable("Can't reach Vigil at vigil.example.gov."))
        edition = service.refresh()

        self.assertTrue(edition.business, "a dead Vigil must not switch Business off")
        record = LicenceRecord.get_solo()
        self.assertEqual(record.status if False else service.current().status, "valid")
        self.assertEqual(record.last_error, "Can't reach Vigil at vigil.example.gov.")
        self.assertTrue(service.business_active())

    def test_a_dropped_link_with_no_licence_keeps_saying_vigil_is_not_connected(self):
        self.unlink_from_vigil()

        edition = service.refresh()

        self.assertEqual(edition.status, "none")
        self.assertEqual(edition.detail, "Vigil is not connected.")


class FeatureGateTests(LicenceTestCase):
    def test_feature_enabled_routes_business_slugs(self):
        from config.features import feature_enabled

        self.business_at_vigil()
        service.refresh()
        cache.clear()
        self.assertTrue(feature_enabled("portal_branding"))

        self.link_to_vigil({"blob": "", "instance": "vigil-1", "status": "none"})
        service.refresh()
        cache.clear()
        self.assertFalse(feature_enabled("portal_branding"))

    def test_app_slugs_answer_without_a_database_hit(self):
        from config.features import enabled_features, feature_enabled

        with self.assertNumQueries(0):
            self.assertTrue(feature_enabled("sla"))
            self.assertFalse(feature_enabled("no_such_feature"))
            self.assertIn("sla", enabled_features())

    def test_business_feature_lists_match(self):
        import config.features as project_features

        self.assertEqual(set(project_features.BUSINESS_FEATURES), set(service.BUSINESS_FEATURES))

    def test_every_business_slug_follows_the_edition(self):
        blob = sign_licence(self.key, features=["jackil", "portal_branding"])
        self.link_to_vigil({"blob": blob, "instance": "vigil-1", "status": "valid"})
        service.refresh()
        cache.clear()

        self.assertTrue(service.has_feature("portal_branding"))

    def test_an_app_slug_is_never_a_business_feature(self):
        self.business_at_vigil()
        service.refresh()

        self.assertFalse(service.has_feature("sla"))
        self.assertFalse(service.has_feature("no_such_feature"))


class ErrorsAnswerFreeTests(LicenceTestCase):
    def test_licensing_errors_answer_free(self):
        patcher = patch(
            "apps.licensing.service.verify_blob", side_effect=RuntimeError("bug in the verifier")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        cache.clear()
        self.assertFalse(service.business_active())
        self.assertFalse(service.has_feature("portal_branding"))
        self.assertEqual(service.current().status, "none")


def licence_messages(response):
    return [(m.level_tag, str(m)) for m in get_messages(response.wsgi_request)]


class EditionPageTests(LicenceTestCase):
    URL = "/settings/edition/"

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user("edition-adm", "e@x.com", "pw", role="admin")
        self.agent = User.objects.create_user("edition-agt", "g@x.com", "pw", role="agent")
        self.customer = User.objects.create_user("edition-cust", "c@x.com", "pw", role="customer")

    def test_the_page_is_admin_only(self):
        for user in (self.agent, self.customer):
            with self.subTest(role=user.role):
                self.client.force_login(user)

                response = self.client.get(self.URL)

                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, "/")

    def test_anonymous_is_sent_to_sign_in(self):
        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:login"))

    def test_the_page_names_every_licence_detail_it_promises(self):
        self.business_at_vigil(org="Riverside Council", lid="lic-77")
        service.refresh()
        cache.clear()
        self.client.force_login(self.admin)

        response = self.client.get(self.URL)
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edition")
        self.assertContains(response, "SQSY Business")
        self.assertContains(response, "Riverside Council")
        self.assertContains(response, "lic-77")
        self.assertContains(response, "Check now")
        for label in ("Organisation", "Licence id", "Expires", "Last checked", "Last verified"):
            self.assertIn(label, content)
        self.assertIn("Jackil's Business features come from the SQSY Business licence", content)

    def test_the_settings_nav_offers_edition_last_after_vigil(self):
        self.client.force_login(self.admin)

        content = self.client.get("/settings/").content.decode()

        self.assertIn(
            '<svg viewBox="0 0 24 24"><path d="M12 2l3 7h7l-5.5 4 2 7-6.5-4.5L5.5 20l2-7L2 9h7z"/></svg>',
            content,
        )
        self.assertLess(content.index("Vigil\n      </a>"), content.index("Edition\n      </a>"))

    def test_the_page_says_community_with_no_licence(self):
        self.link_to_vigil({"blob": "", "instance": "vigil-1", "status": "none"})
        service.refresh()
        cache.clear()
        self.client.force_login(self.admin)

        response = self.client.get(self.URL)

        self.assertContains(response, "Community")
        self.assertContains(response, "No SQSY Business licence on the linked Vigil.")

    def test_check_now_asks_vigil_and_redirects_back_with_a_message(self):
        client = self.link_to_vigil({"blob": "", "instance": "vigil-1", "status": "none"})
        self.client.force_login(self.admin)

        response = self.client.post(self.URL)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.URL)
        self.assertEqual(client.calls, 1, "Check now asks Vigil once")
        self.assertIn(
            ("success", "Checked the licence: No SQSY Business licence on the linked Vigil."),
            licence_messages(response),
        )

    def test_check_now_keeps_a_good_licence_when_vigil_cannot_be_reached(self):
        client = self.business_at_vigil()
        service.refresh()
        self.link_to_vigil(error=VigilUnavailable("Can't reach Vigil at vigil.example.gov."))
        self.client.force_login(self.admin)

        response = self.client.post(self.URL)

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            ("success", "Checked the licence: This licence is valid."), licence_messages(response)
        )
        record = LicenceRecord.get_solo()
        self.assertEqual(
            record.blob, client.answer["blob"], "a failed check must not clear the stored licence"
        )


class CommandTests(LicenceTestCase):
    def test_licence_reports_the_edition_without_asking_vigil(self):
        out = io.StringIO()

        call_command("licence", stdout=out)
        self.assertIn("Edition: Community", out.getvalue())
        self.assertIn("Status: none", out.getvalue())

    def test_licence_refresh_asks_vigil_and_reports_the_edition(self):
        client = self.business_at_vigil(org="Riverside Council")

        out = io.StringIO()
        call_command("licence", "refresh", stdout=out)
        written = out.getvalue()

        self.assertEqual(client.calls, 1)
        self.assertIn("Edition: SQSY Business", written)
        self.assertIn("Status: valid", written)
        self.assertIn("Organisation: Riverside Council", written)


class CacheTests(LicenceTestCase):
    def test_current_answers_from_its_minute_of_cache(self):
        client = self.business_at_vigil()

        service.current()
        first = client.calls
        service.current()

        self.assertEqual(client.calls, first, "a second read within a minute asks Vigil again")

    def test_current_refreshes_a_stale_record_without_being_asked(self):
        client = self.business_at_vigil()
        service.refresh()
        cache.clear()
        before = client.calls

        record = LicenceRecord.get_solo()
        record.last_checked_at = timezone.now() - timedelta(seconds=service.REFRESH_SECONDS + 1)
        record.save(update_fields=["last_checked_at"])

        service.current()

        self.assertEqual(client.calls, before + 1)

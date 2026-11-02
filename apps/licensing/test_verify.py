"""Tests for apps.licensing.verify — the blob format and the signature."""

import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.test import SimpleTestCase

from apps.licensing.verify import PREFIX, Claims, LicenceError, verify_blob


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()


def blob_for(private_key, **claims) -> str:
    payload = {
        "instance": "vigil-1",
        "org": "Example Council",
        "seats": 50,
        "exp": 4_000_000_000,
        "iat": 1_700_000_000,
        "sites": None,
        "lid": "lic-1",
    }
    payload.update(claims)
    body = json.dumps(payload).encode()
    return f"{PREFIX}.{_b64u(body)}.{_b64u(private_key.sign(body))}"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class VerifyBlobTests(SimpleTestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public_key = public_key_b64(self.key)

    def test_reads_the_claims_of_a_genuine_licence(self):
        claims = verify_blob(blob_for(self.key), self.public_key)
        self.assertIsInstance(claims, Claims)
        self.assertEqual(claims.instance, "vigil-1")
        self.assertEqual(claims.org, "Example Council")
        self.assertEqual(claims.seats, 50)
        self.assertEqual(claims.lid, "lic-1")
        self.assertIsNone(claims.sites)

    def test_absent_features_are_every_business_feature(self):
        from apps.licensing.service import BUSINESS_FEATURES

        claims = verify_blob(blob_for(self.key), self.public_key)
        self.assertEqual(set(claims.features), set(BUSINESS_FEATURES) | {"jackil"})

    def test_a_listed_feature_set_is_kept_as_it_says(self):
        blob = blob_for(self.key, features=["jackil", "portal_branding"])
        self.assertEqual(verify_blob(blob, self.public_key).features, ("jackil", "portal_branding"))

    def test_a_signature_from_another_key_is_invalid(self):
        other = Ed25519PrivateKey.generate()
        with self.assertRaises(LicenceError) as ctx:
            verify_blob(blob_for(other), self.public_key)
        self.assertIn("signature", str(ctx.exception))

    def test_a_changed_payload_under_a_real_signature_is_invalid(self):
        parts = blob_for(self.key).split(".")
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        claims["seats"] = 999
        forged = f"{PREFIX}.{_b64u(json.dumps(claims).encode())}.{parts[2]}"
        with self.assertRaises(LicenceError):
            verify_blob(forged, self.public_key)

    def test_a_junk_blob_is_invalid(self):
        for junk in ["", "   ", "not-a-licence", f"{PREFIX}.junk.junk"]:
            with self.subTest(blob=junk), self.assertRaises(LicenceError):
                verify_blob(junk, self.public_key)

    def test_an_unknown_prefix_is_invalid(self):
        blob = blob_for(self.key).replace(PREFIX, "SQSY-LICENSE-V2", 1)
        with self.assertRaises(LicenceError):
            verify_blob(blob, self.public_key)

    def test_no_trusted_key_means_no_licence(self):
        with self.assertRaises(LicenceError):
            verify_blob(blob_for(self.key), "")

    def test_an_unusable_trusted_key_is_a_plain_error(self):
        with self.assertRaises(LicenceError):
            verify_blob(blob_for(self.key), "not base64 at all!")


class AbsentFeaturesTests(SimpleTestCase):
    """Vigil's convention: a licence that lists no features grants them all,
    and Vigil's Business set includes Jackil."""

    def test_a_licence_without_a_feature_list_includes_jackil(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        from apps.licensing.tests import public_key_b64, sign_licence

        key = Ed25519PrivateKey.generate()
        claims = verify_blob(sign_licence(key), public_key_b64(key))
        self.assertIn("jackil", claims.features)

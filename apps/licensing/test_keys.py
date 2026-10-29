"""Which SQSY signing key Jackil trusts, depending on how it is built."""

import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from apps.licensing import keys


class TrustedPublicKeyTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_a_release_build_ignores_the_env_key(self):
        (self.base / keys.RELEASE_MARKER).write_text("", encoding="utf-8")

        self.assertEqual(
            keys.trusted_public_key(
                self.base, debug=True, environ={keys.PUBLIC_KEY_ENV_VAR: "abc"}
            ),
            keys.PRODUCTION_PUBLIC_KEY,
        )

    def test_a_source_checkout_uses_the_env_key(self):
        self.assertEqual(
            keys.trusted_public_key(
                self.base, debug=False, environ={keys.PUBLIC_KEY_ENV_VAR: " abc "}
            ),
            "abc",
        )

    def test_a_debug_checkout_falls_back_to_the_development_key(self):
        self.assertEqual(
            keys.trusted_public_key(self.base, debug=True, environ={}), keys.DEV_PUBLIC_KEY
        )

    def test_a_plain_source_checkout_trusts_nothing(self):
        self.assertEqual(keys.trusted_public_key(self.base, debug=False, environ={}), "")

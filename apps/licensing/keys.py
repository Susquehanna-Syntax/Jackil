"""Which SQSY signing key Jackil trusts, depending on how it is built.

Mirrors Vigil's key arrangement: a release build (one carrying the
``RELEASE_BUILD`` marker file) trusts only the production key and ignores the
environment; a source checkout uses ``JACKIL_LICENSE_PUBLIC_KEY`` if set, else
the development key when DEBUG, else nothing.

This module imports nothing from Django or from Jackil, so ``config/settings.py``
can read it while settings are still being built.
"""

import os
from pathlib import Path

PRODUCTION_PUBLIC_KEY = ""
DEV_PUBLIC_KEY = "HDIgm72yEkIopWgvsv0Q6Gp695l4ecOZMYnP2by7+IQ="
RELEASE_MARKER = "RELEASE_BUILD"
PUBLIC_KEY_ENV_VAR = "JACKIL_LICENSE_PUBLIC_KEY"


def is_release_build(base_dir) -> bool:
    return (Path(base_dir) / RELEASE_MARKER).exists()


def trusted_public_key(base_dir, *, debug: bool, environ=None) -> str:
    """The base64 public key to verify licences against, or "" for none."""
    environ = os.environ if environ is None else environ
    if is_release_build(base_dir):
        return PRODUCTION_PUBLIC_KEY
    env_key = (environ.get(PUBLIC_KEY_ENV_VAR) or "").strip()
    if env_key:
        return env_key
    return DEV_PUBLIC_KEY if debug else ""

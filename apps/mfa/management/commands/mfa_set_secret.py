"""Sets a known, confirmed TOTP secret for a test account.

Local development only: DEBUG is the switch that says this machine is a
development box, and printing an enrolment QR or a secret elsewhere would be
exactly the hole this app exists to close.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import now

from ...models import MfaProfile


class Command(BaseCommand):
    help = "Set and confirm a known TOTP secret for a user (test environments only)."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("base32")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "mfa_set_secret only runs when DEBUG is on — it installs a "
                "secret you already know, which no real deployment should do."
            )
        username = options["username"]
        secret = "".join(options["base32"].split()).upper().rstrip("=")
        if not secret:
            raise CommandError("The secret is empty.")

        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"No user {username!r}.") from exc

        profile, _ = MfaProfile.objects.get_or_create(user=user)
        profile.totp_secret = secret
        profile.totp_confirmed_at = now()
        profile.last_totp_code = ""
        profile.last_totp_used_at = None
        profile.save()
        self.stdout.write(self.style.SUCCESS(f"Authenticator set for {username}."))

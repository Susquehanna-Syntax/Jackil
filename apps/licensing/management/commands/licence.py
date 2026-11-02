"""The edition page, and how to re-check the licence from the command line.

``licence refresh`` goes back to Vigil; without an argument it only reports what
Jackil already knows.
"""

from django.core.management.base import BaseCommand

from apps.licensing import service


class Command(BaseCommand):
    help = "Show, or re-check, the SQSY licence edition this Jackil is running."

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            nargs="?",
            default="status",
            choices=["status", "refresh"],
            help="refresh asks Vigil for the licence again first.",
        )

    def handle(self, *args, **options):
        edition = service.refresh() if options["action"] == "refresh" else service.current()
        claims = edition.claims
        self.stdout.write(f"Edition: {'SQSY Business' if edition.business else 'Community'}")
        self.stdout.write(f"Status: {edition.status}")
        self.stdout.write(f"Detail: {edition.detail}")
        if claims is not None:
            if claims.org:
                self.stdout.write(f"Organisation: {claims.org}")
            if claims.lid:
                self.stdout.write(f"Licence id: {claims.lid}")
            if claims.expiry_date is not None:
                self.stdout.write(f"Expires: {claims.expiry_date:%d %b %Y}")

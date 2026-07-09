from django.core.management.base import BaseCommand

from apps.sla.service import check_and_flag_breaches, escalate
from apps.tickets.models import Ticket


class Command(BaseCommand):
    help = "Flag SLA breaches on open tickets and escalate."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        qs = Ticket.objects.filter(status__in=["open", "in_progress", "pending"])
        breached = 0
        for ticket in qs:
            newly = check_and_flag_breaches(ticket)
            if newly:
                breached += 1
                if not options["dry_run"]:
                    escalate(ticket, newly)
                self.stdout.write(
                    f"#{ticket.id} {ticket.title[:40]} — breached: {', '.join(newly)}"
                )
        self.stdout.write(f"Checked {qs.count()} tickets, {breached} newly breached.")

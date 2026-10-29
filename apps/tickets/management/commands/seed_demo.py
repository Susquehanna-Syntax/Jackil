"""Seed the database with realistic demo data for local development and testing.

Idempotent-ish: running twice creates duplicate tickets but reuses users and
departments (matched by username / name). Use ``--fresh`` to wipe tickets first.
"""

import datetime
import random
from decimal import Decimal
from itertools import cycle

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.items.models import Item, ItemKind
from apps.links.models import DynamicLink
from apps.links.service import LinkError, add_link
from apps.portals.models import Portal
from apps.projects import service as projects_service
from apps.projects.models import Issue, IssueEvent, PersonRate, Project, Sprint
from apps.tickets.models import Ticket
from apps.wiki.models import Page, Space
from apps.wiki.service import save_version

_AVATAR_COLORS = {
    "lavender": (186, 168, 232),
    "mint": (126, 221, 181),
    "peach": (240, 184, 136),
    "sky": (130, 196, 238),
    "rose": (242, 160, 184),
    "coral": (240, 144, 128),
    "lemon": (226, 212, 120),
}


def _make_avatar(initial, color_name, size=200):
    """A square PNG data URI — an initial on a pastel background (demo avatars)."""
    import base64
    import io

    from PIL import Image, ImageDraw, ImageFont

    bg = _AVATAR_COLORS.get(color_name, _AVATAR_COLORS["lavender"])
    img = Image.new("RGB", (size, size), color=bg)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(size * 0.5)
        )
    except OSError:
        font = ImageFont.load_default()
    text = (initial or "?").upper()[:1]
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
        text,
        font=font,
        fill=(28, 28, 33),
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


DEPARTMENTS = [
    ("IT Support", "Hardware, software, accounts and access."),
    ("Facilities", "Building, desks, badges and physical space."),
    ("Human Resources", "Onboarding, benefits and people questions."),
    ("Finance", "Invoices, expenses and procurement."),
]

#: (name, kind, department, vendor, warranty days from today, notes, attributes)
ITEMS = [
    (
        "Mail server",
        "Server",
        "IT Support",
        "Dell",
        730,
        "Runs the internal mail relay. Patched on the second Tuesday each month.",
        {"Serial": "DLX-7741-Q", "Rack": "B4", "IP": "10.20.4.11", "Host": "mail-01"},
    ),
    (
        "File server",
        "Server",
        "IT Support",
        "HPE",
        400,
        "Home drives and the shared projects share. Nightly backup to the NAS.",
        {"Serial": "HPEQ-2210-8", "Rack": "B4", "IP": "10.20.4.12", "Host": "files-01"},
    ),
    (
        "Edge firewall",
        "Network device",
        "IT Support",
        "Fortinet",
        1000,
        "Terminates both office uplinks. Changes follow the firewall change process.",
        {"Serial": "FTN-90331-2", "Rack": "A1", "IP": "10.20.1.1", "Host": "fw-edge-01"},
    ),
    (
        "Core switch",
        "Network device",
        "IT Support",
        "Aruba",
        700,
        "Stack of two in the comms room; every access switch uplinks here.",
        {"Serial": "ARB-55120-7", "Rack": "A1", "IP": "10.20.2.2", "Host": "sw-core-01"},
    ),
    (
        "Office Wi-Fi",
        "Service",
        "IT Support",
        "Aruba",
        None,
        "Two SSIDs: staff (802.1X) and guests (captive portal).",
        {"SSID": "northline-staff", "Controller": "10.20.2.9"},
    ),
    (
        "Payroll app",
        "Application",
        "Human Resources",
        "Brightpath",
        300,
        "Vendor-hosted. Single sign-on through the internal directory.",
        {"URL": "https://payroll.example.com", "Version": "2026.2"},
    ),
    (
        "Microsoft 365 licence pool",
        "Licence",
        "IT Support",
        "Microsoft",
        365,
        "Renewed each October with the annual IT contract.",
        {"Plan": "Business Premium", "Seats": "140", "Used": "128"},
    ),
    (
        "VPN gateway",
        "Service",
        "IT Support",
        "Fortinet",
        None,
        "Split-tunnel VPN for laptops off site.",
        {"Endpoint": "vpn.example.com", "Pool": "10.20.50.0/24"},
    ),
    (
        "Backup NAS",
        "Server",
        "IT Support",
        "Synology",
        450,
        "Holds 35 days of snapshots for the file server and the mail server.",
        {"Serial": "SYN-4471-K", "Rack": "B5", "IP": "10.20.4.30", "Host": "nas-01"},
    ),
    (
        "Badge system",
        "Other",
        "Facilities",
        "HID",
        1400,
        "Door controllers and the reception reader; managed by Facilities.",
        {"Reader": "reception-01", "Firmware": "3.11.2"},
    ),
]

RUNBOOK = """# Mail relay runbook

The internal relay on **mail-01** (`10.20.4.11`) accepts mail from the
office network. Queue depth should stay under 200 messages.

> [!WARNING]
> Restarting the relay during the 07:00-09:00 mail peak bounces thousands of
> messages to the backup MX. Drain the queue first.

## Daily checks

1. Check the queue: `mailq | head -20`
2. Compare throughput with the weekly average: $r = \\frac{n}{t}$.

## Hosts

| Host | Role | Address |
| --- | --- | --- |
| mail-01 | primary relay | `10.20.4.11` |
| mx-backup | secondary MX | `mx-backup.example.com` |

## Capacity

The relay is sized so the backlog never outruns the uplink:

$$\\sum_{i=1}^{n} q_i \\le C$$

## After an outage

- [x] Confirm the queue drained
- [ ] Tell the service desk the incident is over

Restore from snapshot if the disk is unreadable - see [[Backup NAS restore]].
The incident behind this runbook was [[ticket:MAIL_TICKET_ID]].

```bash
systemctl status relay
tail -n 100 /var/log/relay/delivery.log | grep deferred
mailq --flush
```
"""

BACKUP_RESTORE = """# Backup NAS restore

All snapshots live on **nas-01** (`10.20.4.30`) under `/volume1/snapshots`.
We keep 35 days; anything older is pruned by the nightly job.

## Before you restore

- [ ] Confirm the incident is a data problem, not a config problem
- [ ] Note the snapshot timestamp you intend to roll back to
- [ ] Get a written go-ahead from the service desk lead

## Restore steps

1. Put the host into maintenance so monitoring stays quiet.
2. Stop the application that owns the data directory.
3. Mount the snapshot read-only and copy what you need:

```bash
mkdir -p /mnt/snap
mount -o ro //nas-01/snapshots /mnt/snap
rsync -a /mnt/snap/mail-01/2026-09-30/ /srv/relay/spool/
umount /mnt/snap
```

4. Start the service and watch the queue for ten minutes.
5. Lift maintenance and close the restore task.

> [!NOTE]
> A full-host restore takes about 40 minutes for mail-01. Partial file
> restores are usually under five - prefer those.
"""

VPN_TROUBLESHOOTING = """# VPN troubleshooting

Most calls are one of three things: a stale certificate, a laptop that
roamed to the guest VLAN, or a firewall rule that forgot the new address pool.

> [!TIP]
> Ask the user for the exact time the tunnel dropped. The gateway logs every
> 300 seconds, so "somewhere around lunchtime" costs you an hour of grep.

## First five minutes

- [ ] Confirm the user is on the staff Wi-Fi, not the guest SSID
- [ ] Check the pool: `10.20.50.0/24` has 200 addresses and a 4-hour lease
- [ ] Look for `reason=PeerNotResponding` in the gateway log

## Gateway settings that matter

```yaml
vpn:
  endpoint: vpn.example.com
  tunnel_pool: 10.20.50.0/24
  lease_hours: 4
  idle_timeout_minutes: 5
  split_tunnel: true
  keepalive_seconds: 20
```

If the idle timeout is below 60 seconds, roaming laptops will keep dropping -
that was the cause of the VPN tickets last month. Raise it, then ask the
user to reconnect once.

## Still failing

- [ ] Export the client log and attach it to the ticket
- [ ] Rotate the certificate from the directory
- [ ] Escalate to the network queue if the gateway itself is restarting
"""

FIREWALL_PROCESS = """# Firewall change process

**fw-edge-01** carries both office uplinks. One bad rule takes the whole
building offline, so every change follows this path.

## The process

1. Open a ticket with the rule, the reason, and who asked for it.
2. Paste the proposed change in the network queue for review.
3. Schedule inside a change window: 18:00-21:00 weekdays, never Friday.
4. Snapshot the running config before you touch anything.
5. Apply, verify, and keep the rollback command in your terminal.

> [!CAUTION]
> Never edit the management interface rule. It is how you get back in.

## Post-mortem: 2026-05-14 blackout

| Item | Detail |
| --- | --- |
| Impact | 34 minutes, both uplinks down |
| Cause | A cleanup removed an address object still used by the DNS rule |
| Detected by | The card terminal at reception, not monitoring |
| Fix | Restored the object from the pre-change snapshot |

What we changed since:

- [x] The config snapshot is step 4 and is verified before applying
- [x] Monitoring polls the external interface every 60 seconds
- [ ] An address-object usage report before every cleanup

Rules are reviewed each quarter; stale ones get a ticket, not a delete.
"""

STARTER_CHECKLIST = """# New starter checklist

Start a copy of this page for each new starter and rename it to their name.
Do it the week **before** day one - accounts take longer than laptops.

## Before day one

- [ ] Create the directory account and the mailbox
- [ ] Assign a Microsoft 365 seat from the licence pool
- [ ] Add the account to the staff Wi-Fi group
- [ ] Book a desk and issue a badge at reception
- [ ] Order hardware from the stock list on the file server share

## Day one

- [ ] Greet them and walk the floor: kitchen, print room, comms room door
- [ ] Hand over the laptop and let them set their own password
- [ ] Enrol the laptop in the VPN and confirm the tunnel from home
- [ ] Point them at the Help Center for password resets

## Week one

- [ ] Confirm they can reach the shared projects drive
- [ ] Ask their manager whether any line-of-business app is missing
- [ ] Close the onboarding ticket

> [!TIP]
> Payroll access is requested by the manager, never by IT. Send them the
> Brightpath access form instead of guessing at a role.
"""

PASSWORD_RESET = """# Reset your password

You can reset your own password any time from the sign-in screen. It takes
about two minutes and you will need your phone.

## Steps

1. On the sign-in page, choose **Forgot password**.
2. Type your work email address - the one on your badge.
3. We send a six-digit code to your phone. It expires in ten minutes.
4. Enter the code, then choose a new password.

## Making a password that lasts

- [ ] At least 12 characters
- [ ] Not a password you use anywhere else
- [ ] Not your pet, your street, or the year you started

> [!WARNING]
> The service desk will never ask for your password. If someone calls and
> asks for it, hang up and report the call.

## Still stuck?

If the code never arrives, or you changed your phone number, raise a ticket
and choose **Access**. We reset accounts within one working day.
"""

OFFICE_WIFI = """# Connect to the office Wi-Fi

There are two networks. Staff use the private one; visitors use the guest one.

## Staff devices

1. Choose **northline-staff** from the Wi-Fi list.
2. When asked, use your work account - the same one you sign in with.
3. Accept the security certificate prompt.

Your phone joins the same way. On a laptop, tick *connect automatically*
so the VPN tunnel and your drives come back when you sit down.

## Visitors

Choose **northline-guest** and open any web page. The welcome screen asks
for your name and a mobile number, then gives you three hours of access.

| Network | Who | How long |
| --- | --- | --- |
| northline-staff | staff and company devices | while your account is active |
| northline-guest | visitors | 3 hours per session |

> [!TIP]
> If your device keeps joining the guest network, forget it and rejoin
> **northline-staff**. Guest access cannot reach shared drives or printers.

Still no signal? Tell us which floor and the nearest room number when you
raise a ticket - that tells us which access point to look at.
"""

#: (space name, icon colour, order, page specs). A spec with children lists them
#: after its parent so a re-run finds the parent title already present.
SPACES = [
    (
        "Servers",
        "sky",
        10,
        [
            {
                "title": "Mail relay runbook",
                "summary": "How to watch, restart and restore the internal mail relay.",
                "body": RUNBOOK,
                "children": [
                    {
                        "title": "Backup NAS restore",
                        "summary": "Restoring a server from the nightly NAS snapshot.",
                        "body": BACKUP_RESTORE,
                    }
                ],
            }
        ],
    ),
    (
        "Networking",
        "mint",
        20,
        [
            {
                "title": "VPN troubleshooting",
                "summary": "Why the VPN drops, and what to change first.",
                "body": VPN_TROUBLESHOOTING,
            },
            {
                "title": "Firewall change process",
                "summary": "How a rule reaches fw-edge-01 without an outage.",
                "body": FIREWALL_PROCESS,
            },
        ],
    ),
    (
        "Onboarding",
        "lavender",
        30,
        [
            {
                "title": "New starter checklist",
                "summary": "What IT sets up for someone joining the office.",
                "body": STARTER_CHECKLIST,
                "published": True,
            }
        ],
    ),
    (
        "Help Center",
        "lemon",
        40,
        [
            {
                "title": "Reset your password",
                "summary": "Change or recover your password without calling the desk.",
                "body": PASSWORD_RESET,
                "published": True,
            },
            {
                "title": "Connect to the office Wi-Fi",
                "summary": "Joining the staff and guest wireless networks.",
                "body": OFFICE_WIFI,
                "published": True,
            },
        ],
    ),
]

#: Made-up hourly rates for the agents, so the project cost table has numbers.
AGENT_RATES = [("aria", "48.00"), ("dev", "44.00"), ("sam", "52.00"), ("lena", "41.50")]

AGENTS = [
    ("aria", "Aria", "Nakamura", "lavender"),
    ("dev", "Dev", "Okafor", "mint"),
    ("sam", "Sam", "Whitfield", "sky"),
    ("lena", "Lena", "Rossi", "peach"),
]

#: Project rows: key, name, method, lead username, department. A Scrum project
#: reads the sprint list in ``PROJECT_SPRINTS``; anything else gets ``WEB_ISSUES``.
PROJECTS = [
    ("OPS", "IT Operations", "scrum", "aria", "IT Support"),
    ("WEB", "Intranet refresh", "kanban", "dev", ""),
]
PROJECT_DESCRIPTIONS = {
    "OPS": "The rack room, the network, and everything that plugs into both.",
    "WEB": "Bringing the intranet up to date, one page at a time.",
}

#: A sprint's issues: (type, title, description, priority, points, column).
#: The last row of each closed sprint is the one carried over to the next.
PROJECT_SPRINTS = [
    (
        "Sprint 1",
        "Get the rack room and the backup path dependable before winter.",
        [
            (
                "story",
                "Replace the core switch in rack B",
                "Dual PSU, uplinks labelled.",
                "high",
                8,
                "done",
            ),
            (
                "task",
                "Rotate the VPN certificate",
                "Old cert expires this month.",
                "high",
                3,
                "done",
            ),
            (
                "task",
                "Move backups to the new NAS",
                "Copy the seed data, verify a restore.",
                "medium",
                5,
                "done",
            ),
            (
                "bug",
                "Mail relay queue grows after each restart",
                "Deferred mail piles up for an hour.",
                "high",
                2,
                "done",
            ),
            ("task", "Label the patch panels in the comms room", "", "low", 1, "in_progress"),
        ],
    ),
    (
        "Sprint 2",
        "Stand up monitoring so incidents reach the desk before the users do.",
        [
            (
                "story",
                "Add monitoring to the file server shares",
                "Disk, snapshot age, SMB latency.",
                "high",
                5,
                "done",
            ),
            (
                "story",
                "Alert on certificate expiry across all hosts",
                "Two weeks' warning to the queue.",
                "medium",
                5,
                "done",
            ),
            (
                "task",
                "Document the firewall change process",
                "Post it in the Networking space.",
                "medium",
                3,
                "done",
            ),
            (
                "task",
                "Retire the old print server",
                "Move the queues to the new host first.",
                "low",
                3,
                "done",
            ),
            (
                "bug",
                "Guest Wi-Fi captive portal loops on phones",
                "The redirect drops the session.",
                "medium",
                2,
                "todo",
            ),
        ],
    ),
    (
        "Sprint 3",
        "Clear the access backlog and finish the storage migration.",
        [
            (
                "story",
                "Bring the badge readers onto the new firmware",
                "Reception first, then the doors.",
                "medium",
                8,
                "done",
            ),
            (
                "task",
                "Archive last year's project shares",
                "Read-only for twelve months.",
                "medium",
                3,
                "done",
            ),
            (
                "bug",
                "VPN drops on laptops leaving the office Wi-Fi",
                "Idle timeout below the roaming interval.",
                "high",
                3,
                "done",
            ),
            ("task", "Publish the password reset guide to the Help Center", "", "low", 2, "done"),
            ("story", "Trial an attendance kiosk at reception", "", "low", 5, "in_progress"),
        ],
    ),
]

#: The active sprint: (type, title, description, priority, points, column).
#: ``parent`` marks an issue as a sub-task of the story just above it.
ACTIVE_SPRINT_GOAL = "Finish the laptop refresh and cut the file server over."
ACTIVE_SPRINT_ISSUES = [
    (
        "story",
        "Roll out new laptops to the finance team",
        "Image, join the domain, migrate.",
        "medium",
        8,
        "in_progress",
    ),
    ("subtask", "Image the four finance laptops", "", "medium", None, "in_progress"),
    (
        "story",
        "Move the file server shares onto the NAS",
        "Cut over at the weekend.",
        "high",
        5,
        "todo",
    ),
    (
        "bug",
        "Badge reader at the side door loses its network",
        "The PoE injector is suspect.",
        "medium",
        2,
        "todo",
    ),
    ("task", "Review the Microsoft 365 licence pool", "Twelve seats sit unused.", "low", 3, "done"),
    ("subtask", "Cancel the twelve unused seats", "", "low", None, "todo"),
]

#: Backlog issues with no sprint: (type, title, description, priority, points).
OPS_BACKLOG = [
    ("epic", "Office network refresh", "Switches and uplinks on both floors.", "medium", 13),
    ("story", "Plan the office uplink upgrade", "Both circuits renew in March.", "medium", 8),
    ("task", "Replace the printer on the second floor", "Jam-prone; parts are gone.", "low", 2),
    ("bug", "File server share is slow on Mondays", "Antivirus scans the whole volume.", "high", 3),
    ("story", "Add port-level monitoring to the access switches", "", "medium", 5),
    ("task", "Renew the firewall support contract", "", "low", 1),
]

#: The Kanban board's issues, no sprints: (type, title, description, priority, points, column).
WEB_ISSUES = [
    (
        "story",
        "Rewrite the welcome page copy",
        "Say what we do in one sentence.",
        "medium",
        3,
        "todo",
    ),
    ("task", "Collect photographs of each floor", "", "low", 2, "todo"),
    (
        "bug",
        "Old policy PDFs open from the top menu",
        "Four links point at deleted files.",
        "low",
        2,
        "todo",
    ),
    (
        "story",
        "Add a staff directory to the intranet",
        "Search by team and by floor.",
        "high",
        5,
        "in_progress",
    ),
    ("task", "Agree which teams appear on the home page", "", "medium", 1, "in_progress"),
    (
        "epic",
        "Intranet content review",
        "Everything published before 2024.",
        "medium",
        8,
        "in_progress",
    ),
    ("story", "Publish the travel and expenses guide", "", "medium", 3, "done"),
    ("task", "Move the intranet onto the new theme", "", "medium", 5, "done"),
    ("task", "Retire the legacy news page", "Its pages moved to the Wiki.", "low", 2, "done"),
]

CUSTOMERS = [
    ("jordan", "Jordan", "Reyes", "rose"),
    ("priya", "Priya", "Anand", "lemon"),
    ("marcus", "Marcus", "Bell", "coral"),
]
TICKETS = [
    (
        "Laptop won't connect to VPN",
        "Since the update this morning I can't reach the VPN. Error 812.",
        "high",
        "open",
    ),
    (
        "Request new monitor",
        "Would like a second monitor for my desk, 27 inch if possible.",
        "low",
        "open",
    ),
    (
        "Password reset for payroll portal",
        "Locked out of the payroll portal after too many attempts.",
        "medium",
        "in_progress",
    ),
    (
        "Office AC not working on 3rd floor",
        "The AC has been off since Monday, it's getting warm.",
        "medium",
        "open",
    ),
    (
        "New hire onboarding — accounts",
        "Please provision email + Slack for our new designer starting Monday.",
        "high",
        "in_progress",
    ),
    (
        "Expense report rejected",
        "My March expense report was rejected but no reason was given.",
        "low",
        "pending",
    ),
    (
        "Printer on 2nd floor jammed",
        "Paper jam that won't clear, tried the usual steps.",
        "medium",
        "resolved",
    ),
    (
        "Software license for Figma",
        "Need a Figma license for the product team, 3 seats.",
        "medium",
        "open",
    ),
    (
        "Badge not working at side entrance",
        "My badge works at the front but not the side door.",
        "low",
        "closed",
    ),
    (
        "Critical: mail server down",
        "No one in the sales team can send or receive email.",
        "critical",
        "open",
    ),
]


def _pk(obj):
    """The object's pk as a link-end id, or None when the end is missing."""
    return None if obj is None else str(obj.pk)


class Command(BaseCommand):
    help = "Seed demo data (departments, users, tickets, comments)."

    def add_arguments(self, parser):
        parser.add_argument("--fresh", action="store_true", help="Delete existing tickets first.")

    def handle(self, *args, **options):
        if options["fresh"]:
            Ticket.objects.all().delete()
            self.stdout.write(self.style.WARNING("Cleared existing tickets."))

        # Superuser / admin
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@jackil.local",
                "first_name": "Alex",
                "last_name": "Chen",
                "role": "admin",
                "is_staff": True,
                "is_superuser": True,
                "avatar_color": "lavender",
                "avatar": _make_avatar("A", "lavender"),
                "department": "IT Support",
            },
        )
        if created:
            admin.set_password("admin12345")
            admin.save()
            self.stdout.write(self.style.SUCCESS("Created admin / admin12345"))
        if not admin.avatar:
            admin.avatar = _make_avatar("A", "lavender")
            admin.save(update_fields=["avatar"])

        departments = {}
        for name, desc in DEPARTMENTS:
            dept, _ = Department.objects.get_or_create(name=name, defaults={"description": desc})
            departments[name] = dept

        agents = []
        users = {"admin": admin}
        for username, first, last, color in AGENTS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@jackil.local",
                    "first_name": first,
                    "last_name": last,
                    "role": "agent",
                    "avatar_color": color,
                    "avatar": _make_avatar(first[0], color),
                    "department": "IT Support",
                },
            )
            if created:
                user.set_password("password123")
                user.save()
            if not user.avatar:
                user.avatar = _make_avatar(first[0], color)
                user.save(update_fields=["avatar"])
            agents.append(user)
            users[username] = user

        customers = []
        for username, first, last, color in CUSTOMERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.com",
                    "first_name": first,
                    "last_name": last,
                    "role": "customer",
                    "avatar_color": color,
                    "avatar": _make_avatar(first[0], color),
                },
            )
            if created:
                user.set_password("password123")
                user.save()
            if not user.avatar:
                user.avatar = _make_avatar(first[0], color)
                user.save(update_fields=["avatar"])
            customers.append(user)

        dept_list = list(departments.values())
        for title, desc, priority, status in TICKETS:
            ticket = Ticket.objects.create(
                title=title,
                description=desc,
                priority=priority,
                status=status,
                created_by=random.choice(customers),
                assigned_to=random.choice(agents) if status != "open" else None,
                department=random.choice(dept_list),
                tags=random.choice(["", "vpn", "access", "hardware", "urgent,network"]),
            )
            if status in ("resolved", "closed"):
                ticket.closed_at = timezone.now()
                ticket.save()

        items = self._items(departments)
        # Resolved once and shared: this ticket is chipped into the runbook body
        # and is one end of a link, so _wiki and _links must mean the same row.
        # Each _ticket() call takes the newest match, and a run without --fresh
        # leaves older copies of every ticket in the table.
        mail_ticket = _ticket("mail server down")
        pages = self._wiki(admin, _pk(mail_ticket))
        links = self._links(admin, items, pages, _pk(mail_ticket))
        self._projects(admin, users, departments)
        self._portal(departments)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded: {Department.objects.count()} departments, "
                f"{User.objects.count()} users, {Ticket.objects.count()} tickets, "
                f"{Item.objects.count()} items, {Page.objects.count()} pages, {links} links, "
                f"{Project.objects.count()} projects, {Issue.objects.count()} issues."
            )
        )

    def _projects(self, admin, users, departments):
        """The two demo boards: OPS with a sprint history, WEB as a Kanban."""
        if Project.objects.filter(key__in=[key for key, *_ in PROJECTS]).exists():
            return 0
        # Before any issue is done: a done issue freezes its cost from the
        # assignee's rate at that moment. Made-up figures; only admins see them.
        for username, wage in AGENT_RATES:
            PersonRate.objects.get_or_create(
                user=users[username],
                defaults={"hourly_wage": Decimal(wage), "sprint_hours": Decimal("60")},
            )
        assignees = cycle([users[name] for name, *_ in AGENTS])
        created = 0
        for key, name, method, lead, department in PROJECTS:
            project = projects_service.create_project(
                admin,
                key,
                name,
                method=method,
                lead=users[lead],
                description=PROJECT_DESCRIPTIONS[key],
                department=departments.get(department),
            )
            if method == "scrum":
                created += self._scrum_board(admin, project, assignees)
            else:
                created += self._issues(admin, project, assignees, WEB_ISSUES)
                self._backdate_history(project, [])
        return created

    def _scrum_board(self, admin, project, assignees):
        """Three closed sprints of work, an active one, and the backlog behind it."""
        sprints = []
        created = 0

        for name, goal, rows in PROJECT_SPRINTS + [
            ("Sprint 4", ACTIVE_SPRINT_GOAL, ACTIVE_SPRINT_ISSUES)
        ]:
            sprint = Sprint.objects.create(project=project, name=name, goal=goal)
            sprints.append(sprint)
            created += self._issues(admin, project, assignees, rows, sprint=sprint)

        for position, sprint in enumerate(sprints[:3], start=1):
            projects_service.start_sprint(
                admin, sprint, _sprint_start(position), _sprint_end(position)
            )
            open_rows = list(sprint.issues.exclude(column__category="done"))
            projects_service.complete_sprint(admin, sprint)
            for issue in open_rows:
                # Carried over: the service only clears the sprint it was given.
                projects_service.set_sprint(admin, issue, sprints[position])

        projects_service.start_sprint(
            admin, sprints[3], _sprint_start(4), timezone.localdate() + datetime.timedelta(days=9)
        )

        self._issues(admin, project, assignees, OPS_BACKLOG)
        created += len(OPS_BACKLOG)

        self._backdate_history(project, sprints)
        return created

    def _issues(self, admin, project, assignees, rows, sprint=None):
        """One list of issues onto the board: create, place in a column, and go.

        A row is (type, title, description, priority, points) and lands in the
        To do column; with a sixth item it goes to that column instead. A sub-task
        hangs off the issue just above it and takes that agent as its assignee;
        every other issue gets the next agent in the round-robin.
        """
        columns = {column.category: column for column in project.columns.all()}
        last = None
        for row in rows:
            kind, category = row[0], row[5] if len(row) > 5 else "todo"
            subtask = kind == "subtask"
            issue = self._issue(
                admin,
                project,
                # A sub-task's hours belong to whoever owns the story above it.
                last[1] if subtask else next(assignees),
                row,
                sprint=sprint,
                parent=last[0] if subtask else None,
            )
            if not subtask:
                last = (issue, issue.assignee)
            projects_service.move_issue(admin, issue, columns[category])

        return len(rows)

    @staticmethod
    def _issue(admin, project, assignee, row, sprint=None, parent=None):
        """Create, then plan, the way the new-issue form does: the sprint is a
        set_sprint call, which records the "added to sprint" event burndown and
        velocity replay. A sub-task is created straight into its parent's sprint;
        it follows the parent and the charts leave it out."""
        kind, title, description, priority, points = row[:5]
        issue = projects_service.create_issue(
            admin,
            project,
            type=kind,
            title=title,
            description=description,
            priority=priority,
            story_points=points,
            assignee=assignee,
            sprint=sprint if kind == "subtask" else None,
            parent=parent,
        )
        if sprint is not None and kind != "subtask":
            projects_service.set_sprint(admin, issue, sprint)
        return issue

    @staticmethod
    def _backdate_history(project, sprints):
        """Move the board's whole history into the past.

        The service stamps every sprint and event "now", and burndown,
        velocity and cumulative flow replay those events, so left alone every
        chart is flat for weeks and jumps today. Each issue's events are laid
        out along its own story instead: created and planned the day before its
        first sprint starts, moved once that sprint runs, done at its
        completion time, and carried over when the sprint closes. A sprint
        closes at 08:00 and the next starts at 09:00, so carried-over work is
        in scope when it starts.
        """
        now = timezone.now()
        windows = {}
        for position, sprint in enumerate(sprints, start=1):
            start = timezone.make_aware(
                datetime.datetime.combine(_sprint_start(position), datetime.time(9, 0))
            )
            if position <= 3:
                end = timezone.make_aware(
                    datetime.datetime.combine(_sprint_end(position), datetime.time(8, 0))
                )
                Sprint.objects.filter(pk=sprint.pk).update(
                    start_date=_sprint_start(position),
                    end_date=_sprint_end(position),
                    started_at=start,
                    closed_at=end,
                )
            else:
                end = now - datetime.timedelta(hours=1)
                Sprint.objects.filter(pk=sprint.pk).update(
                    start_date=_sprint_start(position), started_at=start
                )
            windows[sprint.pk] = (start, end)

        issues = list(project.issues.order_by("number"))
        for index, issue in enumerate(issues):
            events = list(issue.events.order_by("created_at", "id"))
            first = next((e for e in events if e.kind == "sprint_added"), None)
            if first is not None:
                start, end = windows[first.data["sprint"]]
            else:
                # Backlog and Kanban work arrives over the last four weeks.
                start = now - datetime.timedelta(days=28) + datetime.timedelta(hours=16 * index)
                end = now - datetime.timedelta(hours=2)
            span = end - start
            # Done work finishes somewhere in the back half of its window.
            done_at = start + span * (0.4 + 0.1 * (index % 5)) if issue.completed_at else None
            planned = start - datetime.timedelta(days=1)
            moved_yet = False
            stamp = planned
            for step, event in enumerate(events):
                if event.kind == "moved":
                    to_done = (event.data or {}).get("to_category") == "done"
                    moved_yet = True
                    target = done_at if to_done and done_at else start + span * 0.25
                elif moved_yet:
                    target = end + datetime.timedelta(minutes=1)
                else:
                    target = planned + datetime.timedelta(minutes=step)
                stamp = max(target, stamp + datetime.timedelta(seconds=1))
                IssueEvent.objects.filter(pk=event.pk).update(created_at=stamp)
            Issue.objects.filter(pk=issue.pk).update(created_at=planned, completed_at=done_at)

    def _portal(self, departments):
        """The published IT Support portal; the default portal stays as it is.

        ``Portal.save`` would hand the default to any portal created with
        ``is_default=True``, so this one is never created that way.
        """
        portal, _ = Portal.objects.get_or_create(
            slug="it-support",
            defaults={
                "name": "IT Support",
                "intro": "Report a problem, ask for equipment, or look it up yourself first.",
                "is_published": True,
                "department": departments.get("IT Support"),
                "show_search": True,
                "show_my_tickets": True,
            },
        )
        help_center = Space.objects.filter(name="Help Center").first()
        if help_center is not None:
            portal.spaces.add(help_center)

    def _items(self, departments):
        """The Items register: get_or_create by name, so re-running adds nothing."""
        kinds = {kind.name: kind for kind in ItemKind.objects.all()}
        agents = list(User.objects.filter(role="agent").order_by("username"))
        owner = agents[0] if agents else None
        items = {}
        for name, kind_name, dept_name, vendor, warranty_days, notes, attributes in ITEMS:
            warranty_end = None
            if warranty_days is not None:
                warranty_end = datetime.date.today() + datetime.timedelta(days=warranty_days)
            item, _ = Item.objects.get_or_create(
                name=name,
                defaults={
                    "kind": kinds[kind_name],
                    "owner": owner,
                    "department": departments.get(dept_name),
                    "vendor": vendor,
                    "warranty_end": warranty_end,
                    "notes": notes,
                    "attributes": attributes,
                },
            )
            items[name] = item
        return items

    def _wiki(self, admin, mail_ticket_id):
        """Spaces and pages, skipped when the title already exists in the space."""
        pages = {}
        for space_name, icon, order, page_specs in SPACES:
            space, _ = Space.objects.get_or_create(
                name=space_name, defaults={"icon_color": icon, "order": order}
            )
            for spec in page_specs:
                page = self._page(space, spec, admin, pages, mail_ticket_id)
                if page is None:
                    page = Page.objects.filter(space=space, title=spec["title"]).first()
                for child in spec.get("children", []):
                    self._page(space, child, admin, pages, mail_ticket_id, parent=page)
        return pages

    @staticmethod
    def _page(space, spec, admin, pages, mail_ticket_id, parent=None):
        title = spec["title"]
        if Page.objects.filter(space=space, title=title).exists():
            return None
        page = Page.objects.create(
            space=space,
            parent=parent,
            title=title,
            body=spec["body"].replace("MAIL_TICKET_ID", str(mail_ticket_id)),
            summary=spec["summary"],
            is_published_to_help_center=spec.get("published", False),
            author=admin,
            updated_by=admin,
        )
        save_version(page, admin, "Seeded")
        pages[title] = page
        return page

    def _links(self, admin, items, pages, mail_ticket_id):
        """Dynamic Links, skipping a link whose end is missing."""

        def _linked(source, target, relation):
            """Whether a ticket-end link of this relation already exists.

            Matched by relation and the kinds on each end rather than by pk: a
            run without ``--fresh`` appends another copy of every ticket, so
            the ticket on this end is not the row the last run linked. Either
            direction counts - ``add_link`` will accept a reverse-ordered pair
            of a different relation.

            A link with no ticket end needs no check here: Item and page pks
            are stable, so re-seeding those lands on ``add_link``'s own
            duplicate check and raises ``LinkError``.
            """
            if "ticket" not in (source[0], target[0]):
                return False
            forward = DynamicLink.objects.filter(
                source_type=source[0], target_type=target[0], relation=relation
            )
            backward = DynamicLink.objects.filter(
                source_type=target[0], target_type=source[0], relation=relation
            )
            return (forward | backward).exists()

        mail_item = items.get("Mail server")
        vpn_ticket = _ticket("VPN")
        wanted = [
            (("ticket", mail_ticket_id), ("item", _pk(mail_item)), "affects"),
            (("ticket", _pk(vpn_ticket)), ("item", _pk(items.get("VPN gateway"))), "relates_to"),
            (
                ("page", _pk(pages.get("Mail relay runbook"))),
                ("item", _pk(mail_item)),
                "documented_in",
            ),
            (
                ("ticket", _pk(vpn_ticket)),
                ("page", _pk(pages.get("VPN troubleshooting"))),
                "documented_in",
            ),
        ]

        created = 0
        for source, target, relation in wanted:
            if source[1] is None or target[1] is None:
                continue
            if _linked(source, target, relation):
                continue
            try:
                add_link(admin, source, target, relation)
            except LinkError:
                continue
            created += 1
        return created


def _sprint_start(position):
    """Closed sprint ``position`` (1 = oldest) ran two weeks per cycle."""
    return timezone.localdate() - datetime.timedelta(days=(4 - position) * 14 + 14)


def _sprint_end(position):
    return _sprint_start(position) + datetime.timedelta(days=14)


def _ticket(title_substring):
    """The newest ticket whose title mentions this; a re-run adds another copy."""
    return Ticket.objects.filter(title__icontains=title_substring).order_by("-pk").first()

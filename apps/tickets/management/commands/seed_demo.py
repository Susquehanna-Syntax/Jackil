"""Seed the database with realistic demo data for local development and testing.

Idempotent-ish: running twice creates duplicate tickets but reuses users and
departments (matched by username / name). Use ``--fresh`` to wipe tickets first.
"""

import datetime
import random

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.items.models import Item, ItemKind
from apps.links.models import DynamicLink
from apps.links.service import LinkError, add_link
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

#: (name, kind, department, vendor, warranty years from today, notes, attributes)
ITEMS = [
    (
        "Mail server",
        "Server",
        "IT Support",
        "Dell",
        2,
        "Runs the internal mail relay. Patched on the second Tuesday each month.",
        {"Serial": "DLX-7741-Q", "Rack": "B4", "IP": "10.20.4.11", "Host": "mail-01"},
    ),
    (
        "File server",
        "Server",
        "IT Support",
        "HPE",
        1,
        "Home drives and the shared projects share. Nightly backup to the NAS.",
        {"Serial": "HPEQ-2210-8", "Rack": "B4", "IP": "10.20.4.12", "Host": "files-01"},
    ),
    (
        "Edge firewall",
        "Network device",
        "IT Support",
        "Fortinet",
        3,
        "Terminates both office uplinks. Changes follow the firewall change process.",
        {"Serial": "FTN-90331-2", "Rack": "A1", "IP": "10.20.1.1", "Host": "fw-edge-01"},
    ),
    (
        "Core switch",
        "Network device",
        "IT Support",
        "Aruba",
        2,
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
        1,
        "Vendor-hosted. Single sign-on through the internal directory.",
        {"URL": "https://payroll.example.com", "Version": "2026.2"},
    ),
    (
        "Microsoft 365 licence pool",
        "Licence",
        "IT Support",
        "Microsoft",
        1,
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
        1,
        "Holds 35 days of snapshots for the file server and the mail server.",
        {"Serial": "SYN-4471-K", "Rack": "B5", "IP": "10.20.4.30", "Host": "nas-01"},
    ),
    (
        "Badge system",
        "Other",
        "Facilities",
        "HID",
        4,
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

AGENTS = [
    ("aria", "Aria", "Nakamura", "lavender"),
    ("dev", "Dev", "Okafor", "mint"),
    ("sam", "Sam", "Whitfield", "sky"),
    ("lena", "Lena", "Rossi", "peach"),
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
        mail_ticket = _ticket("mail server down")
        pages = self._wiki(admin, _pk(mail_ticket))
        links = self._links(admin, items, pages)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded: {Department.objects.count()} departments, "
                f"{User.objects.count()} users, {Ticket.objects.count()} tickets, "
                f"{Item.objects.count()} items, {Page.objects.count()} pages, {links} links."
            )
        )

    def _items(self, departments):
        """The Items register: get_or_create by name, so re-running adds nothing."""
        kinds = {kind.name: kind for kind in ItemKind.objects.all()}
        agents = list(User.objects.filter(role="agent").order_by("username"))
        owner = agents[0] if agents else None
        items = {}
        for name, kind_name, dept_name, vendor, warranty_years, notes, attributes in ITEMS:
            warranty_end = None
            if warranty_years is not None:
                today = datetime.date.today()
                warranty_end = today.replace(year=today.year + warranty_years)
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

    def _links(self, admin, items, pages):
        """Dynamic Links, skipping a link whose end is missing.

        Each link is matched with its own rule: Item and page pks are stable,
        so the exact pair identifies them, but a ticket's pk does not - a run
        without ``--fresh`` appends another copy of every ticket - so the links
        that involve one are matched by relation and the kind on the other end.
        """

        def item_end(item):
            return ("item", _pk(item))

        mail_item = items.get("Mail server")
        wanted = [
            (_end(_ticket("mail server down")), item_end(mail_item), "affects", True),
            (_end(_ticket("VPN")), item_end(items.get("VPN gateway")), "relates_to", True),
            (
                _end(pages.get("Mail relay runbook")),
                item_end(mail_item),
                "documented_in",
                False,
            ),
            (
                _end(_ticket("VPN")),
                _end(pages.get("VPN troubleshooting")),
                "documented_in",
                True,
            ),
        ]
        pairs = set(
            DynamicLink.objects.values_list("source_type", "source_id", "target_type", "target_id")
        )
        ticket_relations = {
            (a, b, c)
            for a, b, c in DynamicLink.objects.values_list(
                "source_type", "target_type", "relation"
            ).filter(source_type="ticket")
        }

        created = 0
        for source, target, relation, by_ticket_relation in wanted:
            if source[1] is None or target[1] is None:
                continue
            if by_ticket_relation:
                if (source[0], target[0], relation) in ticket_relations:
                    continue
            elif (source + target) in pairs or (target + source) in pairs:
                continue
            try:
                add_link(admin, source, target, relation)
            except LinkError:
                continue
            created += 1
        return created


def _end(obj):
    """A Dynamic Links end: (type name, pk as text); (None, None) when absent."""
    if obj is None:
        return (None, None)
    kind = "ticket" if isinstance(obj, Ticket) else "page"
    return (kind, str(obj.pk))


def _ticket(title_substring):
    """The newest ticket whose title mentions this; a re-run adds another copy."""
    return Ticket.objects.filter(title__icontains=title_substring).order_by("-pk").first()

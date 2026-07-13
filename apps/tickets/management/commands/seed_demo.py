"""Seed the database with realistic demo data for local development and testing.

Idempotent-ish: running twice creates duplicate tickets but reuses users and
departments (matched by username / name). Use ``--fresh`` to wipe tickets first.
"""

import random

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.tickets.models import Ticket

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

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded: {Department.objects.count()} departments, "
                f"{User.objects.count()} users, {Ticket.objects.count()} tickets."
            )
        )

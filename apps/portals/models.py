"""Portals: what a portal is and how it looks."""

from django.core.exceptions import ValidationError
from django.db import models

ACCENTS = [
    ("lavender", "Lavender"),
    ("sky", "Sky"),
    ("mint", "Mint"),
    ("peach", "Peach"),
    ("rose", "Rose"),
    ("lemon", "Lemon"),
    ("coral", "Coral"),
]

RESERVED_SLUGS = ["new", "admin", "api", "static"]


class Portal(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)
    intro = models.TextField(blank=True, default="")
    is_published = models.BooleanField(default=False)
    #: Exactly one portal is the default; ``save()`` keeps that invariant.
    is_default = models.BooleanField(default=False)
    department = models.ForeignKey(
        "accounts.Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    #: Slugs of the ``customfields`` RequestForms this portal offers.
    request_forms = models.JSONField(default=list, blank=True)
    #: Help-center spaces to show; none chosen means every space.
    spaces = models.ManyToManyField("wiki.Space", blank=True, related_name="+")
    #: The pinned spaces' order on the portal home, as space ids.
    space_order = models.JSONField(default=list, blank=True)
    show_search = models.BooleanField(default=True)
    show_my_tickets = models.BooleanField(default=True)
    #: Slugs of Vigil status pages (stored only until phase 03 embeds them).
    vigil_status_pages = models.JSONField(default=list, blank=True)
    # Styling — Business feature ``portal_branding``.
    logo_url = models.URLField(blank=True, default="")
    accent = models.CharField(max_length=12, choices=ACCENTS, default="lavender")
    custom_css = models.TextField(blank=True, default="")
    hide_powered_by = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Portal.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)

    def clean(self):
        super().clean()
        if self.slug in RESERVED_SLUGS:
            raise ValidationError({"slug": f"“{self.slug}” is a reserved address."})

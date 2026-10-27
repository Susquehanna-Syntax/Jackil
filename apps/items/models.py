from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class ItemKind(models.Model):
    """A category of Item. Ships with six defaults; admins may add more."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True, blank=True)
    #: a pastel name — one of the ``tc-*`` classes in static/css/style.css
    icon_color = models.CharField(max_length=20, default="sky")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:70]
        super().save(*args, **kwargs)


class Item(models.Model):
    """One thing work is about — hand-kept, with or without Vigil."""

    name = models.CharField(max_length=160)
    kind = models.ForeignKey(ItemKind, on_delete=models.PROTECT, related_name="items")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_items",
    )
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True, on_delete=models.SET_NULL
    )
    vendor = models.CharField(max_length=120, blank=True, default="")
    warranty_end = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    #: Free-form extra facts: {"Serial": "XYZ", "Rack": "B4"}.
    attributes = models.JSONField(default=dict, blank=True)
    #: Optional: the Vigil host this Item is. Filled by hand in M3; M6 adds
    #: the picker and live data.
    vigil_host_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("items:item_detail", args=[self.pk])

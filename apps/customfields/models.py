from django.db import models
from django.utils.text import slugify


class CustomField(models.Model):
    FIELD_TYPES = [
        ("text", "Text"),
        ("textarea", "Long text"),
        ("number", "Number"),
        ("dropdown", "Dropdown"),
        ("checkbox", "Checkbox"),
        ("date", "Date"),
    ]

    label = models.CharField(max_length=120)
    key = models.SlugField(max_length=140, unique=True, blank=True)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES, default="text")
    choices = models.TextField(
        blank=True, default="", help_text="One option per line (for dropdown fields)."
    )
    help_text = models.CharField(max_length=200, blank=True, default="")
    required = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "label"]

    def __str__(self):
        return self.label

    def save(self, *args, **kwargs):
        if not self.key:
            base = slugify(self.label)[:140] or "field"
            key = base
            n = 1
            while CustomField.objects.exclude(pk=self.pk).filter(key=key).exists():
                n += 1
                key = f"{base}-{n}"
            self.key = key
        super().save(*args, **kwargs)

    @property
    def choice_list(self):
        return [c.strip() for c in self.choices.splitlines() if c.strip()]


class RequestForm(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.CharField(max_length=255, blank=True, default="")
    intro = models.TextField(blank=True, default="")
    department = models.ForeignKey(
        "accounts.Department", on_delete=models.SET_NULL, null=True, blank=True
    )
    fields = models.ManyToManyField(CustomField, through="RequestFormField", blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:140] or "form"
            slug = base
            n = 1
            while RequestForm.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                n += 1
                slug = f"{base}-{n}"
            self.slug = slug
        super().save(*args, **kwargs)

    def ordered_fields(self):
        return [ff.field for ff in self.form_fields.select_related("field") if ff.field.is_active]


class RequestFormField(models.Model):
    form = models.ForeignKey(RequestForm, on_delete=models.CASCADE, related_name="form_fields")
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("form", "field")]

    def __str__(self):
        return f"{self.form} · {self.field}"


class TicketFieldValue(models.Model):
    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="field_values"
    )
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE)
    value = models.TextField(blank=True, default="")

    class Meta:
        unique_together = [("ticket", "field")]

    def __str__(self):
        return f"{self.field.label}: {self.value}"

    @property
    def display(self):
        if self.field.field_type == "checkbox":
            return "Yes" if self.value in ("on", "true", "1", "yes") else "No"
        return self.value

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class Space(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.CharField(max_length=300, blank=True, default="")
    icon_color = models.CharField(max_length=20, default="lavender")
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)


class Page(models.Model):
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name="pages")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    body = models.TextField(blank=True, default="")
    summary = models.CharField(max_length=300, blank=True, default="")
    #: Internal pages are for agents; a published page also shows in the
    #: customer help center.
    is_published_to_help_center = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    views = models.PositiveIntegerField(default=0)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    #: Who keeps this page true. "Needs attention" lists pages without one.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_pages",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or "page"
            slug = base
            n = 1
            while Page.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                n += 1
                slug = f"{base}-{n}"
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("wiki:page_detail", args=[self.slug])

    def clean(self):
        if self.parent_id is None or self.space_id is None:
            return
        if self.parent_id == self.pk:
            raise ValidationError({"parent": "A page cannot be its own parent."})
        if self.parent.space_id != self.space_id:
            raise ValidationError({"parent": "The parent page must be in the same space."})
        if self.pk is not None and self.parent_id in self.descendant_ids():
            raise ValidationError({"parent": "A page cannot be one of its own descendants."})

    def ancestors(self):
        """Root-first chain of this page's parents. Does not include the page."""
        chain = []
        seen = {self.pk}
        node = self
        while node.parent_id is not None and node.parent_id not in seen:
            node = node.parent
            if node is None:
                break
            seen.add(node.pk)
            chain.append(node)
        chain.reverse()
        return chain

    def descendant_ids(self):
        """Ids of every page below this one, excluding this page."""
        if self.pk is None:
            return set()
        children: dict[int | None, list[int]] = {}
        for pk, parent_id in Page.objects.values_list("pk", "parent_id"):
            children.setdefault(parent_id, []).append(pk)
        found: set[int] = set()
        frontier = [self.pk]
        while frontier:
            current = frontier.pop()
            for child in children.get(current, []):
                if child not in found:
                    found.add(child)
                    frontier.append(child)
        return found


class PageVersion(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    summary = models.CharField(max_length=200, blank=True, default="")

    #: "what changed", in the editor's words
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["page", "number"], name="unique_page_version_number")
        ]
        ordering = ["-number"]

    def __str__(self):
        return f"{self.page_id} v{self.number}"


class PageAttachment(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="wiki/%Y/%m/")
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True, default="")
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_name


class PageTemplate(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField()
    is_builtin = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

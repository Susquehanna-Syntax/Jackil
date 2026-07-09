from django.db import models
from django.utils.text import slugify


class KBCategory(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.CharField(max_length=255, blank=True, default="")
    icon_color = models.CharField(max_length=20, default="lavender")
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "KB categories"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)


class KBArticle(models.Model):
    category = models.ForeignKey(
        KBCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="articles"
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    summary = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField()
    author = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True)
    is_published = models.BooleanField(default=True)
    is_public = models.BooleanField(
        default=True, help_text="Visible to customers in the help center."
    )
    views = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or "article"
            slug = base
            n = 1
            while KBArticle.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                n += 1
                slug = f"{base}-{n}"
            self.slug = slug
        super().save(*args, **kwargs)

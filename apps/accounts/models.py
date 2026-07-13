from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class JackilUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # A superuser is a Jackil admin by default.
        extra_fields.setdefault("role", "admin")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    ROLE_CHOICES = [
        ("customer", "Customer"),
        ("agent", "Support Assistant"),
        ("admin", "Admin"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="customer")
    department = models.CharField(max_length=100, blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")
    avatar_color = models.CharField(max_length=20, default="lavender")
    avatar = models.TextField(
        blank=True, default="", help_text="Base64-encoded profile image data URI"
    )
    preferences = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = JackilUserManager()

    def __str__(self):
        return self.get_username()

    @property
    def avatar_initials(self):
        parts = self.get_full_name().split()
        if len(parts) > 1:
            return f"{parts[0][0]}{parts[-1][0]}"
        return self.username[:2].upper()


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

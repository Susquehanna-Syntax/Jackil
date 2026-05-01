from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("agent", "Agent"),
        ("user", "User"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="user")
    department = models.CharField(max_length=100, blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")
    avatar_color = models.CharField(max_length=20, default="lavender")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
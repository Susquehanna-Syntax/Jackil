from django.contrib import admin

from .models import Inbox


@admin.register(Inbox)
class InboxAdmin(admin.ModelAdmin):
    list_display = ["name", "email_address", "is_default", "active"]

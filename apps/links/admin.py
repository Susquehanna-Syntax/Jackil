from django.contrib import admin

from .models import DynamicLink


@admin.register(DynamicLink)
class DynamicLinkAdmin(admin.ModelAdmin):
    list_display = [
        "source_type",
        "source_id",
        "target_type",
        "target_id",
        "relation",
        "created_at",
    ]
    list_filter = ["relation", "source_type", "target_type"]

from django.contrib import admin

from .models import ApiKey, Webhook


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ["name", "masked", "user", "is_active", "last_used_at"]
    readonly_fields = ["key"]


@admin.register(Webhook)
class WebhookAdmin(admin.ModelAdmin):
    list_display = ["name", "event", "url", "is_active", "last_status"]
    list_filter = ["event", "is_active"]

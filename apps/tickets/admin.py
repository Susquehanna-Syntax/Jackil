from django.contrib import admin

from .models import Attachment, Ticket, TicketMessage


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "status",
        "priority",
        "created_by",
        "assigned_to",
        "department",
        "created_at",
    ]
    list_filter = ["status", "priority", "department"]
    search_fields = ["title", "description"]
    readonly_fields = ["created_at", "updated_at", "closed_at"]
    actions = ["bulk_open", "bulk_in_progress", "bulk_close"]

    def bulk_open(self, request, queryset):
        queryset.update(status="open")

    bulk_open.short_description = "Set selected tickets to Open"

    def bulk_in_progress(self, request, queryset):
        queryset.update(status="in_progress")

    bulk_in_progress.short_description = "Set selected tickets to In Progress"

    def bulk_close(self, request, queryset):
        queryset.update(status="closed")

    bulk_close.short_description = "Set selected tickets to Closed"


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ["ticket", "author", "kind", "is_public", "created_at"]
    list_filter = ["kind", "is_public"]
    search_fields = ["body"]


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ["ticket", "message", "original_name", "size_display", "created_at"]
    list_filter = ["content_type"]

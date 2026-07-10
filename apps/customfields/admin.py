from django.contrib import admin

from .models import CustomField, RequestForm, RequestFormField, TicketFieldValue


class RequestFormFieldInline(admin.TabularInline):
    model = RequestFormField
    extra = 1


@admin.register(CustomField)
class CustomFieldAdmin(admin.ModelAdmin):
    list_display = ["label", "key", "field_type", "required", "is_active"]


@admin.register(RequestForm)
class RequestFormAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active"]
    inlines = [RequestFormFieldInline]


admin.site.register(TicketFieldValue)

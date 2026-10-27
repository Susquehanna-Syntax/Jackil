from django.contrib import admin

from .models import Item, ItemKind


@admin.register(ItemKind)
class ItemKindAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "icon_color", "order"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "owner", "vendor", "warranty_end"]
    list_filter = ["kind"]
    search_fields = ["name", "vendor", "notes"]

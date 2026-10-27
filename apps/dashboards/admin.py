from django.contrib import admin

from .models import Dashboard, DashboardWidget


@admin.register(Dashboard)
class DashboardAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "is_default", "shared", "created_at"]
    list_filter = ["is_default", "shared"]
    search_fields = ["name", "owner__username"]


@admin.register(DashboardWidget)
class DashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ["kind", "dashboard", "x", "y", "w", "h"]
    list_filter = ["kind"]

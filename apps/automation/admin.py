from django.contrib import admin

from .models import AutomationRule, Macro


@admin.register(Macro)
class MacroAdmin(admin.ModelAdmin):
    list_display = ["name", "is_shared", "created_by"]


@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = ["name", "trigger", "is_active", "order", "run_count"]
    list_filter = ["trigger", "is_active"]

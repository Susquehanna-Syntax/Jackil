from django.contrib import admin

from .models import (
    Column,
    CostSettings,
    Issue,
    IssueComment,
    IssueEvent,
    PersonRate,
    Project,
    Sprint,
)


class ColumnInline(admin.TabularInline):
    model = Column
    extra = 0


class SprintInline(admin.TabularInline):
    model = Sprint
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "method", "lead", "department", "is_archived"]
    list_filter = ["method", "is_archived"]
    search_fields = ["key", "name"]
    inlines = [ColumnInline, SprintInline]


@admin.register(Column)
class ColumnAdmin(admin.ModelAdmin):
    list_display = ["project", "name", "category", "order", "wip_limit"]
    list_filter = ["category"]


@admin.register(Sprint)
class SprintAdmin(admin.ModelAdmin):
    list_display = ["project", "name", "state", "start_date", "end_date", "closed_at"]
    list_filter = ["state", "project"]


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ["key", "type", "title", "project", "status", "assignee", "story_points"]
    list_filter = ["type", "priority", "project"]
    search_fields = ["title", "description"]

    @admin.display(description="Column")
    def status(self, obj):
        return obj.column.name if obj.column else ""


@admin.register(IssueComment)
class IssueCommentAdmin(admin.ModelAdmin):
    list_display = ["issue", "author", "created_at"]


@admin.register(IssueEvent)
class IssueEventAdmin(admin.ModelAdmin):
    list_display = ["issue", "kind", "actor", "created_at"]
    list_filter = ["kind"]


@admin.register(PersonRate)
class PersonRateAdmin(admin.ModelAdmin):
    list_display = ["user", "hourly_wage", "sprint_hours"]


@admin.register(CostSettings)
class CostSettingsAdmin(admin.ModelAdmin):
    list_display = ["currency", "default_hours_per_point", "show_cost_totals_to_agents"]

    def has_add_permission(self, request):
        return not CostSettings.objects.exists()

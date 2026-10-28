from django.contrib import admin

from .models import Page, PageAttachment, PageTemplate, PageVersion, Space


@admin.register(Space)
class SpaceAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "icon_color", "order"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ["title", "space", "parent", "is_published_to_help_center", "updated_at"]
    list_filter = ["space", "is_published_to_help_center"]
    search_fields = ["title", "body"]


@admin.register(PageVersion)
class PageVersionAdmin(admin.ModelAdmin):
    list_display = ["page", "number", "title", "author", "created_at"]


@admin.register(PageAttachment)
class PageAttachmentAdmin(admin.ModelAdmin):
    list_display = ["original_name", "page", "size", "uploaded_by", "created_at"]


@admin.register(PageTemplate)
class PageTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "is_builtin", "order"]

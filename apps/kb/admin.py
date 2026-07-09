from django.contrib import admin

from .models import KBArticle, KBCategory


@admin.register(KBCategory)
class KBCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "icon_color", "order")


@admin.register(KBArticle)
class KBArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "author", "is_published", "is_public", "views")
    prepopulated_fields = {"slug": ("title",)}

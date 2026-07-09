from django.contrib import admin

from .models import Department, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["username", "email", "role", "department", "first_name", "last_name"]
    list_filter = ["role", "department"]
    search_fields = ["username", "email", "first_name", "last_name"]


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]

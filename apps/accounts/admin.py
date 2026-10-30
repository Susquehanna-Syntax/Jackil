from django.contrib import admin, messages

from apps.mfa import service as mfa_service

from .models import Department, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["username", "email", "role", "department", "first_name", "last_name"]
    list_filter = ["role", "department"]
    search_fields = ["username", "email", "first_name", "last_name"]
    actions = ["reset_mfa"]

    @admin.action(description="Reset two-factor sign-in")
    def reset_mfa(self, request, queryset):
        staff = request.user.is_superuser or request.user.role == "admin"
        if not staff:
            self.message_user(request, "Admins only.", level=messages.ERROR)
            return None
        reset = 0
        for user in queryset.exclude(pk=request.user.pk):
            mfa_service.reset(user)
            self.log_change(request, user, "Two-factor sign-in reset.")
            reset += 1
        self.message_user(request, f"Two-factor sign-in reset for {reset} user(s).")
        return None


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]

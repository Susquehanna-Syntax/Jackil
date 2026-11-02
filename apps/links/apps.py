from django.apps import AppConfig


class LinksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.links"
    verbose_name = "Dynamic Links"

    def ready(self):
        from apps.links.builtin import register_builtin_types

        register_builtin_types()

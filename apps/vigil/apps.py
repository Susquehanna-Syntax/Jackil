from django.apps import AppConfig


class VigilConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.vigil"
    verbose_name = "Vigil"

    def ready(self):
        from apps.vigil.links import register_vigil_types

        register_vigil_types()

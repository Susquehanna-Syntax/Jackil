from django.apps import AppConfig


class SlaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sla"

    def ready(self):
        from . import receivers  # noqa: F401

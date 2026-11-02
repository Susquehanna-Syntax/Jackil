from django.apps import AppConfig


class WikiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.wiki"
    verbose_name = "Wiki"

    def ready(self):
        from apps.links.registry import register_type

        from .links import PageResolver

        register_type("page", PageResolver())

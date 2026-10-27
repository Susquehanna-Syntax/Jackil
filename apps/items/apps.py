from django.apps import AppConfig


class ItemsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.items"
    verbose_name = "Items"

    def ready(self):
        from apps.items.links import register_item_type

        register_item_type()

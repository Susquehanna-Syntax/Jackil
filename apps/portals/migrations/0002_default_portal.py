from django.db import migrations

PORTAL = {
    "name": "Help center",
    "slug": "help",
    "intro": "Find answers or ask us for help.",
    "is_published": True,
    "is_default": True,
}


def create_default_portal(apps, schema_editor):
    Portal = apps.get_model("portals", "Portal")
    if not Portal.objects.exists():
        Portal.objects.create(**PORTAL)


class Migration(migrations.Migration):
    dependencies = [("portals", "0001_initial")]

    operations = [migrations.RunPython(create_default_portal, migrations.RunPython.noop)]

from django.db import migrations

DEFAULT_KINDS = [
    ("Server", "server", "sky", 10),
    ("Application", "application", "lavender", 20),
    ("Service", "service", "mint", 30),
    ("Network device", "network-device", "peach", 40),
    ("Licence", "licence", "lemon", 50),
    ("Other", "other", "rose", 60),
]


def create_default_kinds(apps, schema_editor):
    ItemKind = apps.get_model("items", "ItemKind")
    for name, slug, icon_color, order in DEFAULT_KINDS:
        ItemKind.objects.update_or_create(
            name=name,
            defaults={"slug": slug, "icon_color": icon_color, "order": order},
        )


def delete_default_kinds(apps, schema_editor):
    ItemKind = apps.get_model("items", "ItemKind")
    ItemKind.objects.filter(name__in=[k[0] for k in DEFAULT_KINDS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("items", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_kinds, delete_default_kinds),
    ]

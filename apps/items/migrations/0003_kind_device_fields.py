from django.db import migrations, models

#: The seeded kinds Vigil will keep as devices once Vigil is connected.
DEVICE_KINDS = {
    "server": "server",
    "network-device": "switch",
}


def seed_device_fields(apps, schema_editor):
    ItemKind = apps.get_model("items", "ItemKind")
    for slug, device_type in DEVICE_KINDS.items():
        ItemKind.objects.filter(slug=slug).update(
            is_device_like=True, vigil_device_type=device_type
        )


class Migration(migrations.Migration):
    dependencies = [
        ("items", "0002_default_kinds"),
    ]

    operations = [
        migrations.AddField(
            model_name="itemkind",
            name="is_device_like",
            field=models.BooleanField(
                default=False, help_text="Kept in Vigil as a device once Vigil is connected."
            ),
        ),
        migrations.AddField(
            model_name="itemkind",
            name="vigil_device_type",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.RunPython(seed_device_fields, migrations.RunPython.noop),
    ]

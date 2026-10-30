from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("items", "0003_kind_device_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="vigil_device_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]

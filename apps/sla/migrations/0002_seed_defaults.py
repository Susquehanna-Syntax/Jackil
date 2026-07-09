from django.db import migrations


def seed_defaults(apps, schema_editor):
    BusinessSchedule = apps.get_model("sla", "BusinessSchedule")
    SLATarget = apps.get_model("sla", "SLATarget")

    if SLATarget.objects.count() == 0:
        BusinessSchedule.objects.get_or_create(
            name="Default schedule",
            defaults={"mode": "24_7"},
        )
        SLATarget.objects.bulk_create(
            [
                SLATarget(priority="critical", response_minutes=60, resolution_minutes=240),
                SLATarget(priority="high", response_minutes=120, resolution_minutes=480),
                SLATarget(priority="medium", response_minutes=240, resolution_minutes=1440),
                SLATarget(priority="low", response_minutes=480, resolution_minutes=2880),
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("sla", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_defaults, migrations.RunPython.noop),
    ]

from django.db import migrations


def seed(apps, schema_editor):
    CustomField = apps.get_model("customfields", "CustomField")
    RequestForm = apps.get_model("customfields", "RequestForm")
    RequestFormField = apps.get_model("customfields", "RequestFormField")
    if CustomField.objects.exists():
        return
    asset = CustomField.objects.create(label="Asset tag", key="asset-tag", field_type="text", help_text="Sticker on the device, e.g. LT-2043", order=0)
    os_field = CustomField.objects.create(label="Operating system", key="operating-system", field_type="dropdown", choices="macOS\nWindows\nLinux\nOther", required=True, order=1)
    urgent = CustomField.objects.create(label="Blocking my work", key="blocking-my-work", field_type="checkbox", order=2)
    seats = CustomField.objects.create(label="Number of seats", key="number-of-seats", field_type="number", help_text="For software/license requests", order=3)
    hw = RequestForm.objects.create(name="Hardware / device issue", slug="hardware-device-issue", description="Problems with a laptop, monitor, or peripheral", intro="Tell us about the device and what's going wrong. Include the asset tag if you can find it.", order=0)
    RequestFormField.objects.create(form=hw, field=asset, order=0)
    RequestFormField.objects.create(form=hw, field=os_field, order=1)
    RequestFormField.objects.create(form=hw, field=urgent, order=2)
    sw = RequestForm.objects.create(name="Software / license request", slug="software-license-request", description="Request access to an application or seats", order=1)
    RequestFormField.objects.create(form=sw, field=seats, order=0)
    RequestFormField.objects.create(form=sw, field=urgent, order=1)


class Migration(migrations.Migration):
    dependencies = [("customfields", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

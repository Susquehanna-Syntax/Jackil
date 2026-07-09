from django.db import migrations


def seed(apps, schema_editor):
    Macro = apps.get_model("automation", "Macro")
    AutomationRule = apps.get_model("automation", "AutomationRule")
    if Macro.objects.count() == 0:
        Macro.objects.bulk_create([
            Macro(name="Ask for screenshot", body="Could you share a screenshot of the error you're seeing? That will help us pinpoint the issue faster.", is_shared=True),
            Macro(name="Resolved — please confirm", body="We believe this is now resolved. Please try again and let us know if you run into any further trouble.", is_shared=True),
            Macro(name="Password reset steps", body="To reset your password:\n1. Go to the login page and click 'Forgot password'.\n2. Enter your work email.\n3. Follow the link we email you.\nLet us know if it doesn't arrive within a few minutes.", is_shared=True),
        ])
    if AutomationRule.objects.count() == 0:
        AutomationRule.objects.create(
            name="Auto-tag VPN issues",
            trigger="on_create",
            conditions=[{"field": "title", "op": "contains", "value": "vpn"}],
            actions=[{"type": "add_tag", "value": "vpn"}],
            is_active=True,
        )


class Migration(migrations.Migration):
    dependencies = [("automation", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

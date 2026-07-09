# Generated migration for seeding initial KB categories and articles.

from django.db import migrations


def seed_kb(apps, schema_editor):
    KBCategory = apps.get_model("kb", "KBCategory")
    KBArticle = apps.get_model("kb", "KBArticle")

    if KBArticle.objects.count() != 0:
        return

    categories = {
        "getting-started": KBCategory(
            name="Getting Started",
            slug="getting-started",
            icon_color="lavender",
            order=1,
        ),
        "troubleshooting": KBCategory(
            name="Troubleshooting",
            slug="troubleshooting",
            icon_color="sky",
            order=2,
        ),
    }
    for cat in categories.values():
        cat.save()

    KBArticle(
        category=categories["getting-started"],
        title="How to set up your account",
        slug="how-to-set-up-your-account",
        summary="Step-by-step guide to creating and configuring your help desk account.",
        body=(
            "1. Go to the sign-up page and enter your email address.\n"
            "2. Check your inbox for a verification link.\n"
            "3. Click the link and set a strong password.\n"
            "4. Complete your profile with your full name and company.\n"
            "5. You're ready to create and manage tickets."
        ),
        is_published=True,
        is_public=True,
    ).save()

    KBArticle(
        category=categories["troubleshooting"],
        title="Reset your password",
        slug="reset-password",
        summary="Instructions for resetting a forgotten or compromised password.",
        body=(
            "If you can't remember your password, use the forgot-password flow:\n"
            "1. Navigate to the login page.\n"
            "2. Click 'Forgot password?'.\n"
            "3. Enter the email address associated with your account.\n"
            "4. Follow the link in the email to set a new password.\n"
            "5. Log in with your new credentials.\n\n"
            "If you don't receive the email within a few minutes, check your spam folder."
        ),
        is_published=True,
        is_public=True,
    ).save()


def reverse_seed(apps, schema_editor):
    KBArticle = apps.get_model("kb", "KBArticle")
    KBCategory = apps.get_model("kb", "KBCategory")

    KBArticle.objects.all().delete()
    KBCategory.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("kb", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_kb, reverse_seed),
    ]

from django.db import migrations

RUNBOOK = """\
# Runbook

## Purpose

What this runbook covers, and when to use it.

## Before you start

- Who to notify
- What to have ready

## Steps

1. First step
2. Second step
3. Verify the result

## Rollback

How to undo these steps if something goes wrong.

## Contacts

Who to escalate to, with out-of-hours details.
"""

POST_MORTEM = """\
# Post-mortem

## Summary

One paragraph: what happened and how it was fixed.

## Impact

Who was affected, for how long, and how badly.

## Timeline

- When it started
- When we noticed
- When it was resolved

## Root cause

Why it happened.

## What went well

- 

## What to change

- 

## Follow-ups

- [ ] Action with an owner
- [ ] Action with an owner
"""

HOW_TO = """\
# How-to

## Goal

What you end up with when you finish.

## Steps

1. First step
2. Second step

## Troubleshooting

What usually goes wrong, and what to do about it.
"""

BUILTINS = [
    ("Runbook", "Step-by-step for a repeatable procedure.", RUNBOOK, 10),
    ("Post-mortem", "After-action review of an incident.", POST_MORTEM, 20),
    ("How-to", "Teach someone to do a thing.", HOW_TO, 30),
]


def create_builtin_templates(apps, schema_editor):
    PageTemplate = apps.get_model("wiki", "PageTemplate")
    for name, description, body, order in BUILTINS:
        PageTemplate.objects.update_or_create(
            name=name,
            defaults={"description": description, "body": body, "is_builtin": True, "order": order},
        )


def delete_builtin_templates(apps, schema_editor):
    PageTemplate = apps.get_model("wiki", "PageTemplate")
    PageTemplate.objects.filter(name__in=[t[0] for t in BUILTINS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("wiki", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_builtin_templates, delete_builtin_templates),
    ]

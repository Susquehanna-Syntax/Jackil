from django.db import migrations


def copy_comments(apps, schema_editor):
    TicketComment = apps.get_model("tickets", "TicketComment")
    TicketMessage = apps.get_model("tickets", "TicketMessage")
    for c in TicketComment.objects.all():
        TicketMessage.objects.create(
            ticket_id=c.ticket_id,
            author_id=c.author_id,
            kind="reply",
            body=c.body,
            is_public=True,
            created_at=c.created_at,
        )

def noop(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0003_ticket_requester_email_ticket_source_ticketmessage_and_more"),
    ]

    operations = [
        migrations.RunPython(copy_comments, noop),
    ]

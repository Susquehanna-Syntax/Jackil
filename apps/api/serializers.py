from rest_framework import serializers

from apps.tickets.models import Ticket, TicketMessage


class TicketMessageSerializer(serializers.ModelSerializer):
    author = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = TicketMessage
        fields = ["id", "kind", "author", "body", "is_public", "from_email", "created_at"]
        read_only_fields = ["id", "author", "created_at"]


class TicketSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField(read_only=True)
    assigned_to = serializers.StringRelatedField(read_only=True)
    department = serializers.StringRelatedField(read_only=True)
    message_count = serializers.IntegerField(source="messages.count", read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "title",
            "description",
            "status",
            "priority",
            "source",
            "created_by",
            "assigned_to",
            "department",
            "requester_email",
            "tags",
            "message_count",
            "first_response_due",
            "resolution_due",
            "created_at",
            "updated_at",
            "closed_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "assigned_to",
            "department",
            "message_count",
            "first_response_due",
            "resolution_due",
            "created_at",
            "updated_at",
            "closed_at",
        ]

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.tickets.models import Ticket
from apps.tickets.services import post_message

from .serializers import TicketMessageSerializer, TicketSerializer


class IsStaff(permissions.BasePermission):
    """Only agents/admins may use the API."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "role", "") in ("agent", "admin")
        )


class TicketViewSet(viewsets.ModelViewSet):
    serializer_class = TicketSerializer
    permission_classes = [IsStaff]

    def get_queryset(self):
        qs = Ticket.objects.select_related("created_by", "assigned_to", "department")
        status_param = self.request.query_params.get("status")
        priority = self.request.query_params.get("priority")
        if status_param:
            qs = qs.filter(status=status_param)
        if priority:
            qs = qs.filter(priority=priority)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, source="api")

    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "POST":
            body = request.data.get("body", "").strip()
            kind = request.data.get("kind", "reply")
            if kind not in ("reply", "note"):
                kind = "reply"
            if not body:
                return Response({"detail": "body is required."}, status=400)
            msg = post_message(ticket, request.user, body, kind=kind)
            return Response(TicketMessageSerializer(msg).data, status=201)
        qs = ticket.messages.select_related("author").order_by("created_at")
        return Response(TicketMessageSerializer(qs, many=True).data)

"""What Vigil reads from Jackil: links touching a Vigil object, and widgets.

The key's user acts for Vigil, so every view states its authentication
classes — ``Api-Key`` first, sessions second — and the staff permission
explicitly; these URLs are mounted whether or not the ``api`` feature is on.
"""

from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from apps.api.auth import ApiKeyAuthentication
from apps.api.views import IsStaff
from apps.dashboards.data import widget_data
from apps.dashboards.widgets import WIDGET_REGISTRY
from apps.items.models import Item
from apps.links.service import links_for
from apps.vigil.client import TYPES

#: Links one Vigil object may show; a panel with two hundred rows is not a panel.
MAX_LINKS = 100

#: Items that say they are this host; past fifty the list stops being readable.
MAX_ITEMS = 50


@api_view(["GET"])
@authentication_classes([ApiKeyAuthentication, SessionAuthentication])
@permission_classes([IsStaff])
def vigil_links(request):
    type = request.query_params.get("type", "")
    id = request.query_params.get("id", "")
    if type not in TYPES:
        return Response({"error": "Unknown type"}, status=400)
    if not id.strip():
        return Response({"error": "Missing id"}, status=400)

    links = []
    for view in links_for(f"vigil:{type}", id, request.user):
        other = view.other
        if not other.available or other.type.startswith("vigil:"):
            continue
        links.append(
            {
                "relation": view.label,
                "type": other.type,
                "id": other.id,
                "label": other.label,
                "url": request.build_absolute_uri(other.url) if other.url else "",
                "status": other.status,
                "tone": other.tone,
            }
        )
        if len(links) == MAX_LINKS:
            break

    items = []
    if type == "host":
        for item in Item.objects.filter(vigil_host_id=id).order_by("name")[:MAX_ITEMS]:
            items.append(
                {
                    "id": str(item.pk),
                    "name": item.name,
                    "url": request.build_absolute_uri(item.get_absolute_url()),
                }
            )
    return Response({"type": type, "id": id, "links": links, "items": items})


def _drawable(entry: dict) -> bool:
    """Whether every setting this kind offers is one Vigil can draw."""
    settings = entry.get("settings") or {}
    return all(field.get("type") in ("choice", "int") for field in settings.values())


def _translated(field: dict) -> dict:
    if field["type"] == "choice":
        options = field.get("options") or []
        return {
            "type": "choice",
            "label": field.get("label", ""),
            "default": str(field.get("default", "")),
            "choices": [[str(o), str(o)] for o in options],
        }
    return {
        "type": "int",
        "label": field.get("label", ""),
        "default": field.get("default", 1),
        "min": field.get("min", 1),
        "max": field.get("max", 50),
    }


def _offerable(kind: str) -> bool:
    """report_chart's card setting is a report_card, which Vigil cannot draw."""
    if kind == "report_chart" or kind not in WIDGET_REGISTRY:
        return False
    return _drawable(WIDGET_REGISTRY[kind])


@api_view(["GET"])
@authentication_classes([ApiKeyAuthentication, SessionAuthentication])
@permission_classes([IsStaff])
def vigil_widgets(request):
    widgets = [
        {
            "kind": kind,
            "title": entry["label"],
            "description": entry["description"],
            "shape": entry["shape"],
            "settings": {
                name: _translated(field) for name, field in (entry.get("settings") or {}).items()
            },
        }
        for kind, entry in WIDGET_REGISTRY.items()
        if _offerable(kind)
    ]
    return Response({"version": 1, "widgets": widgets})


@api_view(["GET"])
@authentication_classes([ApiKeyAuthentication, SessionAuthentication])
@permission_classes([IsStaff])
def vigil_widget(request, kind: str):
    if not _offerable(kind):
        return Response({"error": "Unknown widget"}, status=404)
    return Response(widget_data(kind, request.query_params.dict(), request.user))

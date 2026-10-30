"""The JSON API the links panel talks to."""

from dataclasses import asdict

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.dashboards.permissions import IsStaffRole

from .registry import (
    get_resolver,
    picker_types,
    type_colour,
    type_label,
    types,
)
from .relations import DEFAULT_RELATION, RELATIONS
from .service import LinkError, add_link, links_for, remove_link

#: Search hits per type; a picker that lists fifty things is not a picker.
SEARCH_LIMIT = 5

#: A tab with nothing typed shows twice as much as a search fills the screen.
RECENT_LIMIT_FACTOR = 2


@api_view(["GET"])
@permission_classes([IsStaffRole])
def links_for_endpoint(request, type, id):
    """Everything linked to one object, plus the relation vocabulary the Add
    link dialog offers. ``type`` is the registered name, not a model."""
    return Response(
        {
            "links": [asdict(view) for view in links_for(type, id, request.user)],
            "relations": [[slug, *labels] for slug, labels in RELATIONS.items()],
        }
    )


@api_view(["POST"])
@permission_classes([IsStaffRole])
def links_add(request):
    data = request.data
    relation = (data.get("relation") or "").strip()
    source = ((data.get("source_type") or "").strip(), str(data.get("source_id") or "").strip())
    target = ((data.get("target_type") or "").strip(), str(data.get("target_id") or "").strip())
    try:
        link = add_link(request.user, source, target, relation or DEFAULT_RELATION)
    except LinkError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    from_side = [
        view
        for view in links_for(link.source_type, link.source_id, request.user)
        if view.link_id == link.pk
    ]
    # links_for drops a link whose other end the caller cannot see; add_link
    # has just checked both ends, so an absent view means it vanished between
    # the two queries.
    if not from_side:
        return Response({"error": "You can't see that."}, status=status.HTTP_400_BAD_REQUEST)
    return Response(asdict(from_side[0]), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsStaffRole])
def links_remove(request, link_id):
    try:
        remove_link(request.user, link_id)
    except LinkError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsStaffRole])
def links_types(request):
    """The picker's tabs: every registered type, in tab order, with its colour."""
    result = []
    for name in picker_types():
        resolver = get_resolver(name)
        result.append(
            {
                "name": name,
                "label": type_label(name),
                "colour": type_colour(name),
                "available": resolver.available(request.user),
            }
        )
    return Response({"types": result})


@api_view(["GET"])
@permission_classes([IsStaffRole])
def links_search(request):
    query = (request.GET.get("q") or "").strip()
    exclude = (
        (request.GET.get("exclude_type") or "").strip(),
        str(request.GET.get("exclude_id") or "").strip(),
    )
    limit = SEARCH_LIMIT * RECENT_LIMIT_FACTOR

    # One tab of the picker. Without `type` the old link panel gets exactly
    # what it got before, until phase 02 replaces it.
    name = (request.GET.get("type") or "").strip()
    if name:
        try:
            resolver = get_resolver(name)
        except KeyError:
            return Response({"error": "Unknown type."}, status=status.HTTP_400_BAD_REQUEST)
        if not resolver.available(request.user):
            return Response({"available": False, "results": []})
        targets = (
            resolver.search(query, request.user, limit)
            if len(query) >= 2
            else resolver.recent(request.user, limit)
        )
        results = [
            {**asdict(target), "type_label": type_label(target.type)}
            for target in targets
            if (target.type, str(target.id)) != exclude
        ]
        return Response({"available": True, "results": results})

    if len(query) < 2:
        return Response({"results": []})
    results = []
    for name in types():
        resolver = get_resolver(name)
        for target in resolver.search(query, request.user, SEARCH_LIMIT):
            # A remote stub — the vigil types until M6 registers real
            # resolvers — has nothing to find and everything it names is
            # unavailable; an unavailable end is never worth linking to.
            if not target.available or (target.type, str(target.id)) == exclude:
                continue
            results.append({**asdict(target), "type_label": type_label(target.type)})
    return Response({"results": results})


@api_view(["GET"])
@permission_classes([IsStaffRole])
def links_preview(request, type: str, id: str):
    """One object's facts, excerpt and current links, for the picker's pane."""
    try:
        resolver = get_resolver(type)
    except KeyError:
        return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    target = resolver.preview(id, request.user)
    if target is None:
        return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(
        {
            "target": {
                **asdict(target),
                "type_label": type_label(type),
                "colour": type_colour(type),
            },
            "links": [asdict(view) for view in links_for(type, id, request.user)],
        }
    )


@api_view(["GET"])
@permission_classes([IsStaffRole])
def links_resolve_url(request):
    url = (request.GET.get("url") or "").strip()
    if url:
        for name in types():
            resolver = get_resolver(name)
            obj_id = resolver.from_url(url)
            if obj_id is None:
                continue
            target = resolver.resolve([obj_id], request.user).get(obj_id)
            if target is not None:
                return Response(
                    {"target": {**asdict(target), "type_label": type_label(target.type)}}
                )
    return Response(
        {"error": "That link doesn't point at anything Jackil knows."},
        status=status.HTTP_404_NOT_FOUND,
    )

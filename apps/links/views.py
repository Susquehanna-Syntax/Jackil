"""The JSON API the links panel talks to."""

from dataclasses import asdict

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.dashboards.permissions import IsStaffRole

from .registry import get_resolver, type_label, types
from .relations import DEFAULT_RELATION, RELATIONS
from .service import LinkError, add_link, links_for, remove_link

#: Search hits per type; a picker that lists fifty things is not a picker.
SEARCH_LIMIT = 5


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
def links_search(request):
    query = (request.GET.get("q") or "").strip()
    if len(query) < 2:
        return Response({"results": []})
    exclude = (
        (request.GET.get("exclude_type") or "").strip(),
        str(request.GET.get("exclude_id") or "").strip(),
    )
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

"""The public portal pages a customer signs in to.

A portal home has the help center's shape — spaces of published wiki pages plus
a search — narrowed to what one portal offers: its spaces, its request forms,
the customer's own open tickets. Articles stay at ``/help/a/<slug>/``.
"""

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Value
from django.db.models.functions import Replace
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from apps.tickets.models import Ticket
from apps.wiki.markdown import render as render_markdown
from apps.wiki.models import Page, Space

from .models import Portal
from .service import form_choices, styling_enabled
from .status import status_embeds

CLOSED_STATUSES = ["resolved", "closed"]
#: Guides a help section shows on the home before "All N guides".
SECTION_GUIDES = 3
#: Hits per group in the live search under the hero.
SUGGEST_LIMIT = 6


def _is_staff(user):
    return getattr(user, "role", None) in ("agent", "admin")


def _get_portal(request, slug):
    portal = get_object_or_404(Portal, slug=slug)
    # A draft is a preview for staff and no such page for everyone else.
    if not portal.is_published and not _is_staff(request.user):
        raise Http404("No such portal.")
    return portal


def default_portal_redirect(request):
    """The redirect to the default published portal, or ``None`` when there is
    none — what makes ``/help/`` its own page again."""
    portal = Portal.objects.filter(is_default=True, is_published=True).first()
    if portal is None:
        return None
    target = redirect("portals:portal", slug=portal.slug)
    query = request.GET.get("q", "").strip()
    if query:
        # The portal home carries the query into its own search box.
        target["Location"] += "?" + urlencode({"q": query})
    return target


def _space_ids(portal):
    """The spaces a portal shows: all of them when it selected none."""
    chosen = list(portal.spaces.values_list("pk", flat=True))
    if chosen:
        return chosen
    return list(Space.objects.values_list("pk", flat=True))


def _pages(portal, *, internal):
    queryset = (
        Page.objects.all() if internal else Page.objects.filter(is_published_to_help_center=True)
    )
    return queryset.filter(space_id__in=_space_ids(portal))


def _sections(portal):
    """Per space: the root published pages and their children, as on help home."""
    spaces = portal.spaces.all() if portal.spaces.exists() else Space.objects.all()
    published = Page.objects.filter(is_published_to_help_center=True).filter(space__in=spaces)
    children: dict[int | None, list[Page]] = {}
    for page in published.filter(parent__isnull=False).order_by("order", "title", "pk"):
        children.setdefault(page.parent_id, []).append(page)
    sections = []
    for space in spaces:
        roots = list(
            published.filter(space=space, parent__isnull=True).order_by("order", "title", "pk")
        )
        if roots:
            sections.append((space, [(root, children.get(root.pk, [])) for root in roots]))
    return sections


def _styling(portal):
    if not styling_enabled():
        return None
    # Custom CSS is inlined into a <style> element: escape every "<" as the
    # CSS "\<" so it can never open a tag and close that element early.
    return {
        "tint": "lav" if portal.accent == "lavender" else portal.accent,
        "logo_url": portal.logo_url,
        "css": portal.custom_css.replace("<", "\\3c "),
    }


def _my_tickets(request, portal):
    if (portal is not None and not portal.show_my_tickets) or _is_staff(request.user):
        return None
    return Ticket.objects.filter(created_by=request.user).exclude(status__in=CLOSED_STATUSES)[:5]


def _ordered_spaces(portal):
    """The help sections a portal pins, in the admin's order; a portal that
    pinned none shows every space with published guides."""
    if portal is not None and portal.spaces.exists():
        spaces = list(portal.spaces.all())
        rank = {pk: i for i, pk in enumerate(portal.space_order or [])}
        return sorted(spaces, key=lambda sp: (rank.get(sp.pk, len(rank)), sp.order, sp.name))
    return list(
        Space.objects.annotate(
            guides=Count("pages", filter=Q(pages__is_published_to_help_center=True))
        )
        .filter(guides__gt=0)
        .order_by("order", "name")
    )


def help_sections(portal):
    """Per pinned space: its most-read published guides and how many it has."""
    sections = []
    for space in _ordered_spaces(portal):
        guides = Page.objects.filter(space=space, is_published_to_help_center=True)
        sections.append(
            {
                "space": space,
                "tint": "lav" if space.icon_color in ("", "lavender") else space.icon_color,
                "guides": list(guides.order_by("-views", "order", "title")[:SECTION_GUIDES]),
                "count": guides.count(),
            }
        )
    return sections


def pinned_forms(portal):
    """``[(slug, name)]``: the portal's pinned forms in order, or every active
    form for the ``/help/`` page that has no portal."""
    choices = form_choices()
    if portal is None:
        return choices
    names = dict(choices)
    return [(slug, names[slug]) for slug in portal.request_forms if slug in names]


def _context(request, portal, query=""):
    staff = getattr(request.user, "role", None) == "admin"
    pinned_slugs = {slug for slug, _ in pinned_forms(portal)}
    pinned_spaces = {entry["space"].pk for entry in help_sections(portal)}
    return {
        "portal": portal,
        "intro_html": render_markdown(portal.intro, user=request.user) if portal else "",
        "forms": pinned_forms(portal),
        # A portal offers its own forms only (a department's portal must not
        # list another department's); /help/ with no portal offers every one.
        "all_forms": pinned_forms(portal),
        "help": help_sections(portal),
        "can_arrange": staff and portal is not None,
        "unpinned_forms": [f for f in form_choices() if f[0] not in pinned_slugs] if staff else [],
        "unpinned_spaces": list(Space.objects.exclude(pk__in=pinned_spaces)) if staff else [],
        "my_tickets": _my_tickets(request, portal),
        "styling": _styling(portal) if portal else None,
        "status_embeds": status_embeds(portal) if portal and portal.vigil_status_pages else [],
        "query": query,
    }


def help_center_context(request):
    """The ``/help/`` page for a site with no published portal: the same
    Help center, offering every active form and every space with guides."""
    return _context(request, None)


@login_required
def portal_home(request, slug):
    ctx = _context(request, _get_portal(request, slug), request.GET.get("q", "").strip())
    return render(request, "portals/home.html", ctx)


@login_required
def portal_search(request, slug):
    portal = _get_portal(request, slug)
    if not portal.show_search:
        raise Http404("This portal has no search.")
    query = request.GET.get("q", "").strip()
    results = _pages(portal, internal=_is_staff(request.user)).filter(
        Q(title__icontains=query) | Q(summary__icontains=query) | Q(body__icontains=query)
    )[:50]
    ctx = _context(request, portal, query)
    ctx["results"] = results
    ctx["total"] = results.count()
    ctx["search_page"] = True
    return render(request, "portals/search.html", ctx)


@login_required
def default_portal(request):
    target = default_portal_redirect(request)
    if target is None:
        raise Http404("No published default portal.")
    return target


@login_required
def suggest(request, slug=None):
    """What the hero search finds as you type: guides first, then forms.
    Customers only ever get published guides."""
    portal = _get_portal(request, slug) if slug else None
    query = request.GET.get("q", "").strip()[:100]
    if len(query) < 2:
        return JsonResponse({"guides": [], "forms": []})
    spaces = [entry["space"].pk for entry in help_sections(portal)] if portal else None
    # "wifi" should find "Wi-Fi": compare titles with their hyphens taken out too.
    squashed = query.replace("-", "")
    guides = (
        Page.objects.filter(is_published_to_help_center=True)
        .annotate(bare_title=Replace("title", Value("-"), Value("")))
        .filter(
            Q(title__icontains=query)
            | Q(bare_title__icontains=squashed)
            | Q(summary__icontains=query)
            | Q(body__icontains=query)
        )
    )
    if spaces is not None:
        guides = guides.filter(space_id__in=spaces)
    forms = [
        {
            "name": name,
            "url": reverse("tickets:ticket_create") + "?" + urlencode({"form": form_slug}),
        }
        for form_slug, name in form_choices()
        if query.lower() in name.lower()
    ][:SUGGEST_LIMIT]
    return JsonResponse(
        {
            "guides": [
                {
                    "title": page.title,
                    "space": page.space.name,
                    "url": reverse("help:article", args=[page.slug]),
                }
                for page in guides.select_related("space").order_by("-views", "title")[
                    :SUGGEST_LIMIT
                ]
            ],
            "forms": forms,
        }
    )


@login_required
@require_POST
def save_pins(request, slug):
    """Admins arrange a portal's home: which forms and help sections are pinned,
    and in what order. Writes the same fields the portal settings page edits,
    so it carries the same rule as that page: admins only."""
    if getattr(request.user, "role", None) != "admin":
        raise PermissionDenied
    portal = get_object_or_404(Portal, slug=slug)
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Send JSON."}, status=400)
    form_slugs = [str(x) for x in body.get("forms", []) if isinstance(x, str)]
    known = {slug for slug, _ in form_choices()}
    space_ids = [int(x) for x in body.get("spaces", []) if str(x).isdigit()]
    spaces = list(Space.objects.filter(pk__in=space_ids))
    portal.request_forms = [s for s in form_slugs if s in known]
    portal.space_order = [pk for pk in space_ids if any(sp.pk == pk for sp in spaces)]
    portal.save(update_fields=["request_forms", "space_order", "updated_at"])
    portal.spaces.set(spaces)
    return JsonResponse({"forms": portal.request_forms, "spaces": portal.space_order})

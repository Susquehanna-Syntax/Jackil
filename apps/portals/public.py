"""The public portal pages a customer signs in to.

A portal home has the help center's shape — spaces of published wiki pages plus
a search — narrowed to what one portal offers: its spaces, its request forms,
the customer's own open tickets. Articles stay at ``/help/a/<slug>/``.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import urlencode

from apps.tickets.models import Ticket
from apps.wiki.markdown import render as render_markdown
from apps.wiki.models import Page, Space

from .models import Portal
from .service import form_choices, styling_enabled

CLOSED_STATUSES = ["resolved", "closed"]


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
    if not portal.show_my_tickets or _is_staff(request.user):
        return None
    return Ticket.objects.filter(created_by=request.user).exclude(status__in=CLOSED_STATUSES)[:5]


def _context(request, portal, query=""):
    choices = dict(form_choices())
    return {
        "portal": portal,
        "intro_html": render_markdown(portal.intro, user=request.user),
        "forms": [(slug, choices[slug]) for slug in portal.request_forms if slug in choices],
        "sections": _sections(portal),
        "my_tickets": _my_tickets(request, portal),
        "styling": _styling(portal),
        "query": query,
    }


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

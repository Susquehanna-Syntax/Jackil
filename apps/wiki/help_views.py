"""Views for the customer help center: the pages published to it.

The KB's help center is retired; these are its successors, reading wiki pages.
Customers never see an internal page, a link panel or a resolved Dynamic Link —
the renderer decides that from ``request.user``, and nothing here adds one.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .markdown import render as render_markdown
from .models import Page, Space


def _published():
    return Page.objects.filter(is_published_to_help_center=True)


def _visible_to(user):
    """Everything published; staff additionally see the internal pages."""
    if getattr(user, "role", None) in ("agent", "admin"):
        return Page.objects.all()
    return _published()


@login_required
def home(request):
    """``/help/`` is the portal front door; this page remains for a site with
    no published default portal."""
    from apps.portals.public import default_portal_redirect

    to_portal = default_portal_redirect(request)
    if to_portal is not None:
        return to_portal
    query = request.GET.get("q", "").strip()
    if query:
        results = _visible_to(request.user).filter(
            Q(title__icontains=query) | Q(summary__icontains=query) | Q(body__icontains=query)
        )[:50]
        ctx = {
            "query": query,
            "results": results,
            "total": results.count(),
            "spaces": [],
        }
    else:
        published = _published()
        children: dict[int | None, list[Page]] = {}
        for page in published.filter(parent__isnull=False).order_by("order", "title", "pk"):
            children.setdefault(page.parent_id, []).append(page)
        sections = []
        for space in Space.objects.all():
            roots = [
                page
                for page in published.filter(space=space, parent__isnull=True).order_by(
                    "order", "title", "pk"
                )
            ]
            if roots:
                sections.append((space, [(root, children.get(root.pk, [])) for root in roots]))
        ctx = {
            "query": "",
            "results": None,
            "total": published.count(),
            "spaces": sections,
        }
    return render(request, "help/home.html", ctx)


@login_required
def article(request, slug):
    page = get_object_or_404(_published().select_related("space", "author"), slug=slug)
    Page.objects.filter(pk=page.pk).update(views=F("views") + 1)
    ancestors = [each for each in page.ancestors() if each.is_published_to_help_center]
    children = page.children.filter(is_published_to_help_center=True).order_by(
        "order", "title", "pk"
    )
    return render(
        request,
        "help/article.html",
        {
            "page": page,
            "space": page.space,
            "ancestors": ancestors,
            "html": render_markdown(page.body, user=request.user),
            "children": children,
        },
    )


@login_required
def legacy(request, slug):
    """Old ``/help/<slug>/`` links: keep resolving, at the article's new URL."""
    page = Page.objects.filter(slug=slug).first()
    if page is None:
        raise Http404("No such page.")
    if page.is_published_to_help_center:
        return redirect("help:article", slug=page.slug, permanent=True)
    # An internal page is 404 to anyone but staff, exactly like a missing one,
    # so the answer never tells a customer which internal pages exist.
    if getattr(request.user, "role", None) not in ("agent", "admin"):
        raise Http404("No such page.")
    return redirect("wiki:page_detail", slug=page.slug, permanent=True)

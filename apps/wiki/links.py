import re
from dataclasses import replace

from django.utils import timezone

from apps.links.registry import LinkTarget, Resolver, register_type

from .models import Page

#: A path ending /wiki/p/<slug>/, with or without a scheme and host.
_PAGE_URL = re.compile(r"(?:^|/)wiki/p/([a-z0-9]+(?:-[a-z0-9]+)*)/$")

#: Markdown markers stripped from a preview excerpt.
_MARKDOWN_MARKERS = re.compile(r"[\*_`]|#|\[\[|\]\]")


def plain_excerpt(markdown: str, length: int = 240) -> str:
    """The first `length` characters of a page's text, Markdown markers gone."""
    text = _MARKDOWN_MARKERS.sub("", markdown or "")
    text = " ".join(text.split())
    if len(text) <= length:
        return text
    return text[:length].rstrip() + "..."


class PageResolver(Resolver):
    def resolve(self, ids: list[str], user) -> dict[str, LinkTarget]:
        return {
            str(page.pk): _target(page) for page in self._visible(user).filter(pk__in=_numeric(ids))
        }

    def search(self, q: str, user, limit: int) -> list[LinkTarget]:
        term = q.strip()
        if not term:
            return []
        pages = self._visible(user).filter(title__icontains=term)[:limit]
        return [_target(page) for page in pages]

    def recent(self, user, limit: int) -> list[LinkTarget]:
        return [_target(p) for p in self._visible(user).order_by("-updated_at")[:limit]]

    def preview(self, id: str, user) -> LinkTarget | None:
        page = self._visible(user).filter(pk=id).first() if id.isdigit() else None
        if page is None:
            return None
        edited = timezone.localtime(page.updated_at).strftime("%-d %b %Y")
        editor = page.updated_by
        last_edit = f"{editor.get_full_name() or editor.username}, {edited}" if editor else edited
        return replace(
            _target(page),
            facts=(("Space", page.space.name), ("Last edit", last_edit)),
            excerpt=without_title(plain_excerpt(page.body), page.title),
        )

    def from_url(self, url: str) -> str | None:
        match = _PAGE_URL.search(url)
        if match is None:
            return None
        page = Page.objects.filter(slug=match.group(1)).first()
        return None if page is None else str(page.pk)

    @staticmethod
    def _visible(user):
        """Staff reach every page; everyone else only the published ones.

        Not can_view_items(): that one is about the Items register. Page
        visibility follows the same role test tickets use, and publication — what
        a help-center page is entirely about — decides the rest. That rule belongs
        to phase 02's views too: a customer reading a published page must not
        learn from its breadcrumbs which internal pages its author came from.
        """
        pages = Page.objects.all()
        if user is not None and getattr(user, "role", "") in ("admin", "agent"):
            return pages
        return pages.filter(is_published_to_help_center=True)


def without_title(excerpt: str, title: str) -> str:
    """Pages usually open with their own title as a heading; the preview
    already shows the title, so the excerpt starts after it."""
    if title and excerpt.lower().startswith(title.lower()):
        return excerpt[len(title) :].lstrip(" :-")
    return excerpt


def _numeric(ids: list[str]) -> list[int]:
    return [int(i) for i in ids if i.isdigit()]


def _target(page) -> LinkTarget:
    return LinkTarget(
        type="page",
        id=str(page.pk),
        label=page.title,
        url=page.get_absolute_url(),
        status=page.space.name,
        tone="info",
    )


def register_page_type() -> None:
    register_type("page", PageResolver())

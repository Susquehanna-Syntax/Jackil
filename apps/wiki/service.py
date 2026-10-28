"""The wiki service: versioning a page."""

from .models import Page, PageVersion


def save_version(page: Page, user, summary: str = "") -> PageVersion:
    """Snapshot the page's current title and body as its next version."""
    last = page.versions.order_by("-number").first()
    number = 1 if last is None else last.number + 1
    return PageVersion.objects.create(
        page=page,
        number=number,
        title=page.title,
        body=page.body,
        summary=summary[:200],
        author=user,
    )

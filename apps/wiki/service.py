"""The wiki service: versioning a page, what points at it, and what to suggest."""

import re

from django.db.models import Q

from apps.links.service import LinkError, add_link, links_for

from .markdown import extract_links, extract_titles
from .models import Page, PageVersion

__all__ = [
    "backlinks_for",
    "link_pages_of",
    "save_page_links",
    "save_version",
    "suggest_pages",
]

#: The words a ticket's title is trimmed of before it scores pages — all of them
#: topic-free, so everything left names what the ticket is about.
STOP_WORDS = frozenset(
    {
        "with",
        "that",
        "this",
        "from",
        "have",
        "will",
        "your",
        "when",
        "what",
        "there",
        "their",
        "about",
        "cannot",
        "can't",
        "after",
        "before",
    }
)

#: A word this short is rarely the subject on its own.
MIN_WORD = 4

#: A word in the page's title says more than the same word somewhere in its body.
TITLE_WEIGHT = 3

#: A suggestion list of three is the design; a caller may ask for another size.
SUGGEST_LIMIT = 3

#: Words are runs of letters and digits. An apostrophe is not part of one, so
#: "can't" is the two-word run "can" + "t" here and is already gone on length.
_WORDS = re.compile(r"[a-z0-9]+")


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


def backlinks_for(page: Page) -> list[Page]:
    """Pages whose body wikilinks this page's title, excluding the page itself.

    ``body__icontains`` is only a prefilter — asked for "Mail server" it also
    matches ``[[Mail server backup]]`` — so every candidate is confirmed with
    the renderer's own parser, which reads a wikilink as a whole title and
    counts an aliased ``[[Mail server|the mail box]]`` as one too.
    """
    wanted = page.title.lower()
    candidates = Page.objects.exclude(pk=page.pk).filter(body__icontains=f"[[{page.title}")
    linking = (
        other
        for other in candidates
        if wanted in {title.lower() for title in extract_titles(other.body)}
    )
    return sorted(linking, key=lambda other: (other.title.lower(), other.pk))


def save_page_links(page: Page, user) -> None:
    """Every Dynamic Link the page's text names, as the editor's ``relates to``.

    Only what the editor can see is linked — a chip at an object hidden from them
    is a name in prose, not a link anyone may follow — and an already-linked
    target raises ``LinkError``, which is why the loop keeps going instead of
    refusing the save.

    Links are *not* removed when a chip disappears from the text. Someone may
    have added that link by hand in the links panel, and editing a wiki page is
    not the place to undo their work.
    """
    source = ("page", str(page.pk))
    for target in _visible_targets(_link_targets(page), user):
        try:
            add_link(user, source, target, "relates_to")
        except LinkError:
            continue


def _link_targets(page: Page) -> set[tuple[str, str]]:
    """What this body links to: its ``[[type:id]]`` chips, and the pages it wikilinks.

    A wikilink names a page by title, and only the wiki can turn a title into a
    row, so those resolve here rather than through the links registry. A title no
    page answers to names nothing and drops out; so does this page's own title,
    which is a page pointing at itself.
    """
    targets = set(extract_links(page.body))
    wanted = {title.lower() for title in extract_titles(page.body)}
    if not wanted:
        return targets
    targets |= {
        ("page", str(other.pk))
        for other in Page.objects.exclude(pk=page.pk)
        if other.title.lower() in wanted
    }
    return targets


def _visible_targets(targets: set[tuple[str, str]], user) -> set[tuple[str, str]]:
    """The targets this user may see, keyed as the link should be keyed.

    A resolver answers "may this user see it" one type at a time and keys its
    answer by the id it was given — which for a page wikilink is a *title*,
    something only the wiki can turn into a row. So the answer is re-read by
    title as well as by pk, and what comes back is the page's real pk: a chip is
    worth a link, a name is not.
    """
    from apps.links.registry import get_resolver

    visible = set()
    for kind in {kind for kind, _ in targets}:
        try:
            resolver = get_resolver(kind)
        except KeyError:
            continue
        ids = sorted(target_id for target_type, target_id in targets if target_type == kind)
        resolved = resolver.resolve(ids, user)
        by_label = {target.label.lower(): target for target in resolved.values()}
        for wanted in ids:
            seen = resolved.get(wanted) or by_label.get(wanted.lower())
            if seen is not None and seen.available:
                visible.add((kind, seen.id))
    return visible


def link_pages_of(type: str, id: str, user) -> list[Page]:
    """The pages on the far side of a Dynamic Link to this object.

    A link made from a wikilink is addressed by page *title* — that is what the
    text says — so the id half is matched on pk first and on title after.
    """
    wanted = {view.other.id for view in links_for(type, id, user) if view.other.type == "page"}
    if not wanted:
        return []

    numeric = [int(each) for each in wanted if each.isdigit()]
    pages = list(Page.objects.filter(pk__in=numeric))
    titles = [each for each in wanted if not each.isdigit()]
    if titles:
        pages += list(Page.objects.filter(title__in=titles))

    seen = {page.pk: page for page in pages}
    return sorted(seen.values(), key=lambda page: (page.title.lower(), page.pk))


def suggest_pages(ticket, user, limit: int = SUGGEST_LIMIT) -> list[Page]:
    """Articles worth a read while answering this ticket; staff only.

    In order of confidence: the pages already linked to the ticket, the pages
    linked to an Item the ticket is linked to, and last a word match on the
    ticket's title — plain substring matching over titles, summaries and bodies,
    because Postgres full-text is a later release.
    """
    if getattr(user, "role", None) not in ("agent", "admin"):
        return []

    linked = links_for("ticket", str(ticket.pk), user)
    ordered = link_pages_of("ticket", str(ticket.pk), user)
    for other in linked:
        if other.other.type == "item" and other.other.id.isdigit():
            ordered.extend(link_pages_of("item", other.other.id, user))
    ordered.extend(_word_matches(ticket)[:limit])

    seen: set[int] = set()
    suggestions: list[Page] = []
    for page in ordered:
        if page.pk not in seen:
            seen.add(page.pk)
            suggestions.append(page)
        if len(suggestions) == limit:
            break
    return suggestions


def _word_matches(ticket) -> list[Page]:
    """Pages whose words overlap the ticket's title, best score first.

    A word counts once for the page, at the best place it appears: a page whose
    title says two of the ticket's words outranks one whose body says five.
    """
    words = _title_words(ticket.title)
    if not words:
        return []

    query = Q()
    for word in words:
        query |= Q(title__icontains=word) | Q(summary__icontains=word) | Q(body__icontains=word)

    scored = []
    for page in Page.objects.filter(query):
        # A title hit needs the word on its own — "mail" in "Mailboxes" is not
        # the word "mail" — while the body is searched as it comes. A word counts
        # once per page, at the best place it appears: one word the author put in
        # the title outranks three mentions in the prose.
        title = f" {page.title.lower()} "
        rest = f" {page.summary} {page.body}".lower()
        scored.append(
            (
                sum(
                    TITLE_WEIGHT if f" {word} " in title else (1 if word in rest else 0)
                    for word in words
                ),
                page,
            )
        )

    # Best score first; a tie goes to the page edited most recently, then pk so
    # that two pages saved in the same second cannot reorder between requests.
    ranked = sorted(
        scored, key=lambda pair: (-pair[0], -pair[1].updated_at.timestamp(), pair[1].pk)
    )
    return [page for _, page in ranked]


def _title_words(title: str) -> list[str]:
    """The title's topic words: lowercase, 4+ letters, stop words gone."""
    return [
        word
        for word in _WORDS.findall((title or "").lower())
        if len(word) >= MIN_WORD and word not in STOP_WORDS
    ]

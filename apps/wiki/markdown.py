"""The wiki's one Markdown renderer: GFM + LaTeX + callouts + [[links]], sanitised.

Ordering is the whole design. Every ``[[…]]`` becomes a placeholder whose target
lives in a data-* attribute, and nh3 strips that attribute — so on the way through
the sanitiser a link has already forgotten what it points at, and nothing a writer
types can arrive downstream naming an object its reader may not open. The targets
are therefore noted down *before* sanitising and matched against the result
afterwards, where only the shown text is left to go on.

That constrains what a link can become. A chip displays its object's own label, so
the pair (our class, that text) identifies it and survives as something worth
resolving. A wikilink displays whatever the writer typed, so the same pair only
means anything when that text is the title the link was given: an aliased
``[[Onboarding|getting started]]`` becomes the words "getting started". The editor
shows writers their aliases unresolved; a broken page title still offers to create
the page.
"""

import re
from collections import defaultdict
from urllib.parse import quote

import nh3
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt
from mdit_py_plugins.gfm import gfm_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import ClassNotFound, get_lexer_by_name

#: A page body is capped before parsing; past this the renderer works on a
#: truncated copy and says so.
MAX_SOURCE = 200_000

_TRUNCATED_NOTE = (
    '<div class="markdown-alert markdown-alert-note"><p class="markdown-alert-title">Note</p>'
    "<p>This page is very long; only the first part is shown.</p></div>"
)

_WIKI = re.compile(r"\[\[([^\[\]\n|]{1,200})(?:\|([^\[\]\n]{1,200}))?\]\]")

# Each [[…]] becomes one of these two. The named groups are unique across both:
# they are read out of the combined pattern below by name, not by position.
_CHIP_PLACEHOLDER = re.compile(
    r'<span class="dl-chip" data-dl-type="(?P<type>[^"]*)" data-dl-id="(?P<id>[^"]*)"'
    r">(?P<chip_text>.*?)</span>"
)
_WIKILINK_PLACEHOLDER = re.compile(
    r'<a class="wikilink" data-wikilink="(?P<title>[^"]*)">(?P<link_text>.*?)</a>'
)
_PLACEHOLDERS = re.compile(f"{_CHIP_PLACEHOLDER.pattern}|{_WIKILINK_PLACEHOLDER.pattern}")

# What each placeholder is left as once nh3 has taken the target away: our class,
# and the text. Nothing else can produce this pair — a writer's own <a> or <span>
# reaches us with no attribute we allow besides href and title, and href is refused
# for every scheme but http(s) and mailto.
_PASSED_CHIP = re.compile(r'<span class="dl-chip">(?P<text>[^<]*)</span>')
_PASSED_WIKILINK = re.compile(r'<a class="wikilink"[^>]*>(?P<text>[^<]*)</a>')

#: Text to blank before extracting references: a chip written inside code is
#: documentation, not a link. The fence's indentation bound is markdown-it's.
_FENCED_BLOCK = re.compile(
    r"^[ \t]{0,3}(`{3,}|~{3,}).*?\1[ \t]*(?:\r?\n|$)", re.DOTALL | re.MULTILINE
)
_CODE_SPAN = re.compile(r"`[^`\n]*`")

_TONES = {"ok": "tc-mint", "warn": "tc-lemon", "bad": "tc-rose", "info": "tc-sky"}

_ALLOWED_TAGS = nh3.ALLOWED_TAGS | {
    "span",
    "div",
    "input",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "del",
    "sup",
    "sub",
    "section",
    "pre",
    "code",
    "small",
    "hr",
}

# `id` is deliberately absent. nh3 can be told to keep it, but an anchor name a
# writer picks is a hook every later element on the page could be aimed at, and
# neither KaTeX nor phase 02's stylesheet needs one. `style` is allowed only where
# markdown-it emits it itself: aligned table columns.
_ALLOWED_ATTRS = {
    "*": {"class"},
    "a": {"href", "title"},
    "input": {"type", "checked", "disabled"},
    "th": {"style"},
    "td": {"style"},
    "img": {"src", "alt", "title"},
}


def _highlight(code, lang, attrs):
    try:
        lexer = get_lexer_by_name(lang)
    except ClassNotFound:
        return ""  # markdown-it escapes the code itself
    return highlight(code, lexer, HtmlFormatter(nowrap=True))


def render(md: str, *, user, links: bool = True):
    """Render page Markdown to sanitised HTML. Never raises on bad input."""
    source = md or ""
    truncated = len(source) > MAX_SOURCE
    if truncated:
        source = source[:MAX_SOURCE]

    html = _parser().render(source)
    titles, aliased = _wanted_titles(html)
    chips = {
        (m["type"], m["id"]) for m in _PLACEHOLDERS.finditer(html) if m.lastgroup == "chip_text"
    }

    clean = nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )

    # Links are resolved last because they are the one part of the output that
    # depends on who is reading. With no reader there is nothing to resolve
    # against, and a link nobody may open says least as its writer's own words.
    if links and user is not None:
        # Dynamic Links are a staff surface: a customer sees a chip's words, never
        # where it points, even for an object they could open themselves.
        from apps.links.service import can_see_links

        staff = can_see_links(user)
        targets = _chip_targets(chips, user) if staff else {}
        clean = _resolve_links(
            clean, _page_urls(titles, staff=staff), aliased, targets, offer_new=staff
        )
    else:
        clean = _flatten_links(clean)

    if truncated:
        clean = _TRUNCATED_NOTE + clean
    return mark_safe(clean)


def extract_links(body: str) -> set[tuple[str, str]]:
    """The ``(type, id)`` pairs a body's Dynamic Link chips name, code excluded.

    Fenced code blocks and inline code spans are stripped first: a chip written
    inside code is documentation, not a link.
    """
    targets: set[tuple[str, str]] = set()
    for match in _WIKI.finditer(_without_code(body or "")):
        kind, object_id = _split_dynamic_target(match.group(1).strip())
        if kind is not None:
            targets.add((kind, object_id))
    return targets


def extract_titles(body: str) -> set[str]:
    """The page titles a body's wikilinks name, code excluded.

    An aliased ``[[Onboarding|getting started]]`` asks for the page
    "Onboarding" — the alias is what the reader sees, not what is wanted.
    ``[[type:id]]`` chips are not titles: the renderer turns those into Dynamic
    Link chips, so they belong to ``extract_links`` and nothing else.
    """
    titles: set[str] = set()
    for match in _WIKI.finditer(_without_code(body or "")):
        target = match.group(1).strip()
        if _split_dynamic_target(target)[0] is None:
            titles.add(target)
    return titles


def extract_references(body: str) -> tuple[set[str], set[tuple[str, str]]]:
    """What one page body points at: page titles, and Dynamic Link targets."""
    return extract_titles(body), extract_links(body)


def _parser():
    md = MarkdownIt("commonmark", {"html": False, "highlight": _highlight})
    md.use(gfm_plugin, dollarmath=True)
    md.inline.ruler.before("link", "wikilink", _wikilink_rule)
    md.add_render_rule("wikilink", _render_wikilink)
    return md


def _wikilink_rule(state, silent):
    pos = state.pos
    if not state.src.startswith("[[", pos):
        return False
    match = _WIKI.match(state.src, pos)
    if not match:
        return False
    if not silent:
        token = state.push("wikilink", "", 0)
        target, alias = match.group(1).strip(), (match.group(2) or "").strip()
        # The text the reader sees is chosen before escaping runs, so that
        # "unescaped" below can only ever undo what this very renderer put in.
        token.meta = {"target": target, "text": alias if alias else _shown(target)}
    state.pos = match.end()
    return True


def _shown(target: str) -> str:
    """What a link with no |alias shows: its target as written.

    The sanitiser drops the data-* attributes, so a chip is later found again
    by this text ("ticket:12"); a resolved chip replaces it with the object's
    label, and an unresolved one keeps the writer's own words.
    """
    return target


def _render_wikilink(self, tokens, idx, options, env):
    meta = tokens[idx].meta
    target = meta["target"]
    text = meta["text"] or target
    kind, object_id = _split_dynamic_target(target)
    if kind is None:
        return f'<a class="wikilink" data-wikilink="{escape(target)}">{escape(text)}</a>'
    return (
        '<span class="dl-chip" '
        f'data-dl-type="{escape(kind)}" data-dl-id="{escape(object_id)}">{escape(text)}</span>'
    )


def _without_code(md: str) -> str:
    """The body with fenced code blocks and inline code spans blanked out.

    A wikilink written inside code is documentation, not a reference, so every
    extractor in this app runs on this text. markdown-it starts a fence with up
    to three spaces of indentation, which is where the bound comes from.
    """
    return _CODE_SPAN.sub(" ", _FENCED_BLOCK.sub(" ", md or ""))


def _split_dynamic_target(target: str) -> tuple[str | None, str]:
    """The registered link type this target names, or None for a page title.

    ``vigil:*`` type names contain a colon themselves, so the longest registered
    prefix wins and everything after it is the id.
    """
    from apps.links.registry import types

    known = types()
    for kind in sorted(known, key=len, reverse=True):
        prefix = f"{kind}:"
        if target.startswith(prefix) and len(target) > len(prefix):
            return kind, target[len(prefix) :]
    return None, ""


def _wanted_titles(html: str) -> tuple[set[str], set[str]]:
    """Titles worth looking up, and the text of every aliased link.

    An alias is looked up too: its page may not exist, and "no page called X" is a
    fact about the title rather than about who is reading — so the offer to create
    it goes to anyone who can be shown the link at all.
    """
    titles: set[str] = set()
    aliased: set[str] = set()
    for match in _PLACEHOLDERS.finditer(html):
        if match.lastgroup != "link_text":
            continue
        title = match["title"]
        titles.add(title)
        if match["link_text"] != escape(title):
            aliased.add(match["link_text"])
    return titles, aliased


def _page_urls(titles: set[str], *, staff: bool) -> dict[str, str]:
    """Where each wikilink title points, for this reader. A title no page the
    reader may see answers to is absent: a customer's render must not reveal
    that an internal page exists, or its slug."""
    if not titles:
        return {}
    from apps.wiki.models import Page

    pages = Page.objects.all() if staff else Page.objects.filter(is_published_to_help_center=True)
    exact: dict[str, str] = {}
    folded: dict[str, str] = {}
    for slug, title in pages.values_list("slug", "title"):
        exact.setdefault(title, slug)
        folded.setdefault(title.casefold(), slug)

    urls: dict[str, str] = {}
    for title in titles:
        slug = exact.get(title) or folded.get(title.casefold())
        if slug is not None:
            # Customers cannot open /wiki/; a published page is theirs at the help center.
            urls[title] = reverse("wiki:page_detail" if staff else "help:article", args=[slug])
    return urls


def _chip_targets(chips, user) -> dict[tuple[str, str], object]:
    """Resolve each type's chips in one call, keeping only what this reader sees."""
    from apps.links.registry import get_resolver

    wanted: dict[str, set[str]] = defaultdict(set)
    for kind, object_id in chips:
        wanted[kind].add(object_id)

    targets: dict[tuple[str, str], object] = {}
    for kind, ids in wanted.items():
        try:
            resolver = get_resolver(kind)
        except KeyError:
            continue
        for object_id, target in resolver.resolve(sorted(ids), user).items():
            targets[(kind, object_id)] = target
    return targets


def _resolve_links(
    html: str, urls: dict[str, str], aliased: set[str], chips, *, offer_new: bool
) -> str:
    """Chips first, then pages. A chip's text is its object's label and identifies
    it; a wikilink's text is the writer's, so it resolves only when that text is
    the title the link was given and is an ordinary word otherwise."""

    def chip(match: re.Match[str]) -> str:
        shown = match["text"]
        kind, object_id = _split_dynamic_target(_unescaped(shown))
        target = None if kind is None else chips.get((kind, object_id))
        return shown if target is None else _chip_html(target)

    def page(match: re.Match[str]) -> str:
        text = match["text"]
        if text in aliased:  # the alias shows, and what it hides is not ours to name
            return text
        title = _unescaped(text)
        if title in urls:
            return f'<a class="wikilink" href="{escape(urls[title])}">{text}</a>'
        if not offer_new:  # only staff may create pages, so only staff are offered one
            return text
        new_page = f"{reverse('wiki:page_new')}?title={quote(title)}"
        return (
            f'<a class="wikilink broken" href="{escape(new_page)}" '
            f'title="No page called {escape(title)} yet">{text}</a>'
        )

    return _PASSED_WIKILINK.sub(page, _PASSED_CHIP.sub(chip, html))


def _flatten_links(html: str) -> str:
    """Links nobody may open keep only the words their writer chose."""
    return _PASSED_CHIP.sub(r"\g<text>", _PASSED_WIKILINK.sub(r"\g<text>", html))


def _unescaped(text: str) -> str:
    """Undo what the renderer escaped, to compare shown text with a target."""
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&amp;", "&")
    )


def _chip_html(target) -> str:
    classes = ["dl-chip"]
    tint = _TONES.get(target.tone, "")
    if tint:
        classes.append(tint)
    if not target.available:
        classes.append("unavailable")
    label = escape(target.label)
    if target.status:
        label += f"<small>{escape(target.status)}</small>"
    return f'<a class="{" ".join(classes)}" href="{escape(target.url)}">{label}</a>'

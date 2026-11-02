"""Move every Knowledge Base category and article into a "Help Center" space.

Article slugs are kept, because old ``/help/<slug>/`` links must keep resolving
at the article URL. A page's own ``save()`` is what appends ``-2`` to a clashing
slug, and historical models have no custom ``save``, so that loop runs again
here — with the twist the real models never needed: an article wins its slug and
the *category* page that got there first is the one moved.

Because an article takes a name a category page may already hold, the two groups
are written in opposite orders: category pages get a provisional slug — never a
name an article wants, so a swap can never collide with another swap — and the
final pass renames exactly the pages that handed a name over.

Nothing in here asks the table whether a slug is taken. Under ``migrate`` that
question is answered about the state from before the transaction, and when a test
calls this function twice it would be answered about the first run's writes —
which is the same fact worth knowing, provided it is read once, up front. That
snapshot is ``before``; ``held`` is this run's own ledger, and a page listed in it
is a page this run may rename, which is what tells our own category page apart
from an article that came over in an earlier import.
"""

from django.conf import settings
from django.db import migrations
from django.utils.text import slugify

SPACE_NAME = "Help Center"
SPACE_SLUG = "help-center"
DRAFT_PREFIX = "Draft from the Knowledge Base. "
VERSION_SUMMARY = "Imported from the Knowledge Base"


def import_kb(apps, schema_editor):
    Page = apps.get_model("wiki", "Page")
    PageVersion = apps.get_model("wiki", "PageVersion")
    Space = apps.get_model("wiki", "Space")
    KBArticle = apps.get_model("kb", "KBArticle")
    KBCategory = apps.get_model("kb", "KBCategory")

    space, _ = Space.objects.get_or_create(
        slug=SPACE_SLUG,
        defaults={
            "name": SPACE_NAME,
            "description": "Articles moved from the Knowledge Base.",
            "icon_color": "lavender",
        },
    )

    before = set(Page.objects.values_list("slug", flat=True))
    # page pk → slug it currently holds. Only a page in here may be renamed.
    held = {}
    # Each category's page, so an article knows whose name it is taking.
    by_category = {}
    # A category page is published only if an article of its own reaches the
    # help center, which is not known until the articles are placed.
    published_category = {}

    wanted = {article.slug for article in KBArticle.objects.all()}
    for category in KBCategory.objects.order_by("order", "name"):
        # Re-running the import reuses the category's page instead of making a
        # second one beside it (idempotent, like the article loop below).
        existing = Page.objects.filter(
            space=space, parent__isnull=True, title=category.name[:200]
        ).first()
        if existing is not None:
            held[existing.pk] = existing.slug
            by_category[category.pk] = existing.pk
            continue
        base = slugify(category.name)[:200] or "category"
        claimed = _free(held, before, wanted, base)
        page = Page(
            space=space,
            title=category.name[:200],
            slug=claimed,
            body=category.description or "",
            summary=(category.description or "")[:300],
            order=category.order,
            is_published_to_help_center=False,
        )
        page.save()
        held[page.pk] = claimed
        by_category[category.pk] = page.pk
        published_category[page.pk] = any(
            a.is_published and a.is_public for a in category.articles.all()
        )
        _version(PageVersion, page)

    # Articles: they own the slug an old link already points at.
    moving = {}
    for article in KBArticle.objects.order_by("pk"):
        category_pk = by_category.get(article.category_id)
        if article.slug in before and held.get(category_pk) != article.slug:
            # Somebody else answers to that name, and this run may not move
            # them: the article arrived in an earlier import.
            continue
        if category_pk is not None and held.get(category_pk) == article.slug:
            # Our own category page holds it, so the page gives it up and takes
            # the next free name beside it once every article is placed.
            moving[category_pk] = article.slug

        page = _article_page(Page, space, article, category_pk)
        # auto_now overwrites updated_at on save, so the imported date goes in
        # by queryset update afterwards.
        Page.objects.filter(pk=page.pk).update(
            updated_at=article.updated_at,
            is_published_to_help_center=bool(article.is_published and article.is_public),
        )
        held[page.pk] = article.slug
        _version(PageVersion, page)

    for page_pk, published in published_category.items():
        Page.objects.filter(pk=page_pk).update(is_published_to_help_center=published)

    for page_pk, surrendered in moving.items():
        Page.objects.filter(pk=page_pk).update(slug=_relocated(held, before, surrendered))


def _free(held, before, wanted, base):
    """The first free slug after ``base``: not taken, and not an article's.

    A category page never settles on a name an article wants, so no two
    categories can reach for the same replacement name, and the name it does
    hold is one it can hand straight to that article.
    """
    base = (base or "")[:220] or "category"
    taken = set(held.values()) | before
    slug = base
    n = 1
    while slug in taken or slug in wanted:
        n += 1
        slug = f"{base}-{n}"[:220]
    return slug


def _relocated(held, before, surrendered):
    """A relocated category page's slug: the name it gave up, with ``-2`` beside it.

    Counted on from that name because it is where a reader of the ``-2``
    convention expects a moved section to end up.
    """
    taken = set(held.values()) | before
    slug = f"{surrendered}-2"[:220]
    n = 2
    while slug in taken:
        n += 1
        slug = f"{surrendered}-{n}"[:220]
    return slug


def _article_page(Page, space, article, category_pk):
    summary = article.summary[:300]
    if not article.is_published:
        summary = f"{DRAFT_PREFIX}{summary}"[:300]
    page = Page(
        space=space,
        parent_id=category_pk,
        title=article.title[:200],
        slug=article.slug,
        body=article.body or "",
        summary=summary,
        views=article.views,
        author_id=article.author_id,
        is_published_to_help_center=False,
        created_at=article.created_at,
    )
    page.save()
    return page


def _version(PageVersion, page):
    PageVersion.objects.create(
        page=page,
        number=1,
        title=page.title,
        body=page.body,
        summary=VERSION_SUMMARY[:200],
        author_id=page.author_id,
    )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("kb", "0002_seed_kb"),
        ("wiki", "0002_builtin_templates"),
    ]

    operations = [
        migrations.RunPython(import_kb, reverse_code=migrations.RunPython.noop),
    ]

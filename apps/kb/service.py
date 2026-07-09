from django.db.models import Q

from .models import KBArticle, KBCategory


def public_categories():
    return KBCategory.objects.all()


def published_articles(public_only=True):
    qs = KBArticle.objects.filter(is_published=True).select_related("category", "author")
    if public_only:
        qs = qs.filter(is_public=True)
    return qs


def search_articles(query, public_only=True):
    qs = published_articles(public_only=public_only)
    if query:
        qs = qs.filter(
            Q(title__icontains=query) | Q(body__icontains=query) | Q(summary__icontains=query)
        )
    return qs


def record_view(article):
    KBArticle.objects.filter(pk=article.pk).update(views=article.views + 1)


def public_only_for(user):
    """Customers see only public articles; agents/admins see everything."""
    return getattr(user, "role", "customer") == "customer"

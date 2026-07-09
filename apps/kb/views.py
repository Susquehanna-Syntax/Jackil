from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import KBArticle, KBCategory
from .service import public_only_for, record_view, search_articles


@login_required
def help_home(request):
    query = request.GET.get("q", "").strip()
    public_only = public_only_for(request.user)
    articles = search_articles(query, public_only=public_only)
    categories = []
    if not query:
        for cat in KBCategory.objects.prefetch_related("articles"):
            cat_articles = [
                a for a in cat.articles.all() if a.is_published and (not public_only or a.is_public)
            ]
            if cat_articles:
                categories.append((cat, cat_articles))
    ctx = {
        "query": query,
        "results": articles if query else None,
        "categories": categories,
        "total": articles.count() if query else KBArticle.objects.count(),
    }
    return render(request, "kb/help_home.html", ctx)


@login_required
def article_detail(request, slug):
    public_only = public_only_for(request.user)
    qs = KBArticle.objects.filter(is_published=True)
    if public_only:
        qs = qs.filter(is_public=True)
    article = get_object_or_404(qs.select_related("category", "author"), slug=slug)
    record_view(article)
    related = KBArticle.objects.filter(is_published=True, category=article.category).exclude(
        pk=article.pk
    )
    if public_only:
        related = related.filter(is_public=True)
    return render(request, "kb/article.html", {"article": article, "related": related[:4]})

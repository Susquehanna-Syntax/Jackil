from django.http import HttpResponse

#: An anonymous reader is not a phase 01 feature: the help center, phase 02's
#: public pages and phase 03's KB migration all belong to signed-in users. When
#: one reaches a wiki URL there is nothing here to answer with — and rendering a
#: page's links for nobody in particular would mean choosing a permission to
#: resolve them against, which phase 01 must not invent.
_ANONYMOUS = "The wiki needs a signed-in reader."


def page_detail(request, slug):
    return HttpResponse(_ANONYMOUS, status=501, content_type="text/plain")


def page_new(request):
    return HttpResponse(_ANONYMOUS, status=501, content_type="text/plain")

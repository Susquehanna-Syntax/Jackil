from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def render_live(
    request: HttpRequest, template: str, fragment_template: str, context: dict
) -> HttpResponse:
    """The whole page normally; only the results fragment when ?partial=1."""
    if request.GET.get("partial") == "1":
        return render(request, fragment_template, context)
    return render(request, template, context)

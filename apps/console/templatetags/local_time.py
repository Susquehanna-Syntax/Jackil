"""Times in the reader's own zone.

The server keeps and renders UTC; ``{% local_time value %}`` writes that UTC
time (labelled) inside a ``<time>`` element, and jackil-ui.js rewrites it in
the browser's zone. Without script the reader still sees a correct, labelled
time.
"""

import datetime as dt

from django import template
from django.utils.html import format_html

register = template.Library()

_FALLBACK = {
    "datetime": "%-d %b %Y, %H:%M UTC",
    "short": "%b %-d, %H:%M UTC",
}


@register.simple_tag
def local_time(value, style="datetime"):
    if not value:
        return ""
    if style not in _FALLBACK:
        style = "datetime"
    utc = value.astimezone(dt.UTC)
    return format_html(
        '<time datetime="{}" data-local="{}">{}</time>',
        utc.isoformat(),
        style,
        utc.strftime(_FALLBACK[style]),
    )

"""The ``{% links_panel %}`` tag: the Linked panel's server-rendered shell."""

from django import template

from ..service import can_see_links

register = template.Library()


@register.inclusion_tag("links/panel.html", takes_context=True)
def links_panel(context, obj_type, obj_id):
    """Render the panel shell for agents and admins; nothing for anyone else.

    The chip content is filled by ``jackil-links.js`` from the links API, so
    one tag serves every object type — including types this app knows nothing
    about.
    """
    if not can_see_links(context["request"].user):
        return {"hidden": True}
    return {"hidden": False, "obj_type": obj_type, "obj_id": obj_id}

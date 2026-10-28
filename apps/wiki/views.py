"""The wiki screens: spaces, the page tree, the editor, versions.

Staff-only for now (agents and admins); customers read published pages
through the help centre, which is phase 03's surface.
"""

import difflib
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F
from django.http import FileResponse, Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape, mark_safe

from .markdown import render as render_markdown
from .models import Page, PageAttachment, PageTemplate, Space
from .service import save_version

#: The colours a space icon may take — the same set Items offers.
SPACE_COLOURS = ["lavender", "sky", "mint", "peach", "lemon", "rose", "coral"]

#: The body box's ceiling. Well past what the renderer shows in full; the
#: editor refuses anything longer rather than saving a page that lies about
#: its own contents.
MAX_BODY = 1_000_000


def _max_attachment_size():
    return getattr(settings, "MAX_ATTACHMENT_SIZE", 25 * 1024 * 1024)


def _staff_or_403(request):
    if getattr(request.user, "role", None) not in ("agent", "admin"):
        raise PermissionDenied


def _is_admin(request):
    return getattr(request.user, "role", None) == "admin"


def _tree(space, current=None):
    """The space's pages as pre-rendered nested ``<li>`` items.

    Django templates cannot recurse without a template per level, and two
    of these screens want the same tree; depth is carried per row so one
    flat walk becomes the nesting.
    """
    children: dict[int | None, list[Page]] = {}
    for page in space.pages.all().order_by("order", "title", "pk"):
        children.setdefault(page.parent_id, []).append(page)

    def item(page: Page) -> str:
        nested = "".join(item(child) for child in children.get(page.pk, []))
        current_cls = ' class="current"' if current is not None and page.pk == current.pk else ""
        return (
            f'<li><a href="{page.get_absolute_url()}"{current_cls}>'
            f"{escape(page.title)}</a>"
            f"{f'<ul>{nested}</ul>' if nested else ''}</li>"
        )

    html = "".join(item(page) for page in children.get(None, []))
    return mark_safe(html)


def _parents_of(space, page):
    if space is None:
        return []
    return list(space.pages.exclude(pk=page.pk).order_by("title"))


@login_required
def home(request):
    _staff_or_403(request)
    ctx = {
        "spaces": Space.objects.all(),
        "recent": Page.objects.select_related("space", "updated_by").order_by("-updated_at")[:10],
        "can_manage_spaces": _is_admin(request),
    }
    return render(request, "wiki/home.html", ctx)


@login_required
def space_create(request):
    _staff_or_403(request)
    if not _is_admin(request):
        raise PermissionDenied
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "A space needs a name.")
            return redirect("wiki:space_create")
        space, created = Space.objects.get_or_create(name=name[:120])
        if not created:
            messages.error(request, f"“{space.name}” already exists.")
            return redirect("wiki:space_detail", slug=space.slug)
        messages.success(request, f"Space “{space.name}” created.")
        return redirect("wiki:space_detail", slug=space.slug)
    return render(
        request,
        "wiki/space_form.html",
        {"space": None, "submit_label": "Create Space", "colours": SPACE_COLOURS},
    )


@login_required
def space_edit(request, slug):
    _staff_or_403(request)
    if not _is_admin(request):
        raise PermissionDenied
    space = get_object_or_404(Space, slug=slug)
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "A space needs a name.")
            return redirect("wiki:space_edit", slug=space.slug)
        space.name = name[:120]
        space.description = (request.POST.get("description") or "").strip()[:300]
        space.icon_color = (request.POST.get("icon_color") or "lavender").strip()[:20]
        space.save()
        messages.success(request, f"Space “{space.name}” updated.")
        return redirect("wiki:space_detail", slug=space.slug)
    return render(
        request,
        "wiki/space_form.html",
        {"space": space, "submit_label": "Save Changes", "colours": SPACE_COLOURS},
    )


@login_required
def space_detail(request, slug):
    _staff_or_403(request)
    space = get_object_or_404(Space, slug=slug)
    ctx = {
        "space": space,
        "tree": _tree(space),
        "can_manage_spaces": _is_admin(request),
    }
    return render(request, "wiki/space_detail.html", ctx)


@login_required
def page_detail(request, slug):
    _staff_or_403(request)
    page = get_object_or_404(Page.objects.select_related("space", "updated_by"), slug=slug)
    Page.objects.filter(pk=page.pk).update(views=F("views") + 1)

    ctx = {
        "page": page,
        "space": page.space,
        "ancestors": page.ancestors(),
        "html": render_markdown(page.body, user=request.user),
        "children": page.children.all().order_by("order", "title", "pk"),
        "attachments": page.attachments.all(),
        "can_delete": _is_admin(request),
        "tree": _tree(page.space, current=page),
    }
    return render(request, "wiki/page_detail.html", ctx)


def _read_post(request, page):
    """Apply the posted editor to ``page``'s fields and report what refused.

    Validation is ``Page.clean()`` plus the two length limits the model's
    fields cannot express for a textarea; the return is field name → message.
    The error dict keeps its insertion order, so the first message is always
    the first thing that was wrong with the post.

    A rejected save leaves ``page`` holding the attempted values — which is
    what an editor should redraw — but never touches the stored row.
    """
    errors: dict[str, str] = {}
    title = (request.POST.get("title") or "").strip()
    body = request.POST.get("body") or ""

    if not title:
        errors["title"] = "A page needs a title."
    elif len(title) > 200:
        errors["title"] = "Titles are limited to 200 characters."
    if len(body) > MAX_BODY:
        errors["body"] = f"Bodies are limited to {MAX_BODY:,} characters."

    space_slug = (request.POST.get("space") or "").strip()
    space = Space.objects.filter(slug=space_slug).first()
    if space is None:
        errors["space"] = "Pick the space this page lives in."

    parent_slug = (request.POST.get("parent") or "").strip()
    parent = None
    if parent_slug:
        parent = Page.objects.filter(slug=parent_slug).first()
        if parent is None:
            errors["parent"] = "That parent page does not exist."

    page.title = title[:200]
    page.body = body
    if space is not None:
        page.space = space
    page.parent = parent

    try:
        page.clean()
    except ValidationError as exc:
        for field, messages_ in exc.error_dict.items():
            errors.setdefault(str(field), str(messages_[0]))
    return errors


def _editor_context(request, page, *, errors, submit_label, is_new):
    return {
        "page": page,
        "space": page.space,
        "spaces": Space.objects.all(),
        "parents": _parents_of(page.space, page),
        "templates": PageTemplate.objects.all(),
        "errors": errors,
        "submit_label": submit_label,
        "is_new": is_new,
        "preview_html": "" if is_new else render_markdown(page.body, user=request.user),
    }


@login_required
def page_new(request):
    _staff_or_403(request)
    if request.method == "POST":
        page = Page(author=request.user)
        errors = _read_post(request, page)
        if errors:
            return render(
                request,
                "wiki/page_form.html",
                _editor_context(
                    request, page, errors=errors, submit_label="Create Page", is_new=True
                ),
            )
        page.is_published_to_help_center = request.POST.get("is_published") == "on"
        page.updated_by = request.user
        page.save()
        save_version(page, request.user, summary=(request.POST.get("summary") or "").strip())
        messages.success(request, f"Page “{page.title}” created.")
        return redirect(page.get_absolute_url())

    space = Space.objects.filter(slug=request.GET.get("space", "")).first()
    if space is None:
        space = Space.objects.first()
    parent_slug = request.GET.get("parent", "")
    parent = None
    if space is not None and parent_slug:
        parent = Page.objects.filter(space=space, slug=parent_slug).first()

    template_id = request.GET.get("template", "")
    template_pk = int(template_id) if template_id.isdigit() else None
    body = ""
    if template_pk is not None:
        body = (
            PageTemplate.objects.filter(pk=template_pk).values_list("body", flat=True).first() or ""
        )

    page = Page(
        title=(request.GET.get("title") or "")[:200],
        body=body,
        space=space,
        parent=parent,
    )
    ctx = _editor_context(request, page, errors={}, submit_label="Create Page", is_new=True)
    ctx["selected_template"] = template_pk
    return render(request, "wiki/page_form.html", ctx)


@login_required
def page_edit(request, slug):
    _staff_or_403(request)
    page = get_object_or_404(Page, slug=slug)
    if request.method == "POST":
        was_parent = page.parent_id
        errors = _read_post(request, page)
        if errors:
            return render(
                request,
                "wiki/page_form.html",
                _editor_context(
                    request, page, errors=errors, submit_label="Save Changes", is_new=False
                ),
            )
        page.updated_by = request.user
        page.is_published_to_help_center = request.POST.get("is_published") == "on"
        page.save()
        summary = (request.POST.get("summary") or "").strip()
        if page.parent_id != was_parent and not summary:
            summary = "Moved"
        save_version(page, request.user, summary=summary)
        messages.success(request, f"Page “{page.title}” saved.")
        return redirect(page.get_absolute_url())

    return render(
        request,
        "wiki/page_form.html",
        _editor_context(request, page, errors={}, submit_label="Save Changes", is_new=False),
    )


@login_required
def page_history(request, slug):
    _staff_or_403(request)
    page = get_object_or_404(Page, slug=slug)
    return render(
        request,
        "wiki/page_history.html",
        {"page": page, "versions": page.versions.select_related("author").all()},
    )


@login_required
def page_version(request, slug, number):
    _staff_or_403(request)
    page = get_object_or_404(Page, slug=slug)
    version = get_object_or_404(page.versions.select_related("author"), number=number)
    return render(
        request,
        "wiki/page_version.html",
        {
            "page": page,
            "version": version,
            "html": render_markdown(version.body, user=request.user),
        },
    )


def _diff_lines(old_body: str, new_body: str) -> list[tuple[str, str]]:
    """``unified_diff`` output as (class, line) pairs for the template."""
    rows: list[tuple[str, str]] = []
    for line in difflib.unified_diff(old_body.splitlines(), new_body.splitlines(), lineterm=""):
        if line.startswith("+++") or line.startswith("---"):
            rows.append(("ctx", escape(line)))
        elif line.startswith("+"):
            rows.append(("add", escape(line)))
        elif line.startswith("-"):
            rows.append(("del", escape(line)))
        else:
            rows.append(("ctx", escape(line)))
    return rows


@login_required
def page_diff(request, slug):
    _staff_or_403(request)
    page = get_object_or_404(Page, slug=slug)

    def wanted(name):
        raw = request.GET.get(name, "")
        return int(raw) if raw.isdigit() else None

    b = wanted("b")
    if b is None:
        latest = page.versions.order_by("-number").first()
        b = 0 if latest is None else latest.number
    a = wanted("a")
    if a is None:
        a = b - 1

    old = page.versions.filter(number=a).first()
    new = page.versions.filter(number=b).first()
    if old is None or new is None:
        raise Http404("No such version.")

    return render(
        request,
        "wiki/page_diff.html",
        {"page": page, "old": old, "new": new, "lines": _diff_lines(old.body, new.body)},
    )


@login_required
def page_restore(request, slug, number):
    _staff_or_403(request)
    page = get_object_or_404(Page, slug=slug)
    version = get_object_or_404(page.versions, number=number)
    if request.method == "POST":
        page.title = version.title
        page.body = version.body
        page.updated_by = request.user
        page.save()
        save_version(page, request.user, summary=f"Restored version {version.number}")
        messages.success(request, f"Version {version.number} restored.")
    return redirect(page.get_absolute_url())


@login_required
def page_move(request, slug):
    _staff_or_403(request)
    page = get_object_or_404(Page.objects.select_related("space"), slug=slug)
    if request.method != "POST":
        return redirect(page.get_absolute_url())

    parent_slug = (request.POST.get("parent") or "").strip()
    parent = None
    if parent_slug:
        parent = Page.objects.filter(space=page.space, slug=parent_slug).first()
        if parent is None:
            messages.error(request, "That parent page is not in this space.")
            return redirect(page.get_absolute_url())

    page.parent = parent
    try:
        page.clean()
    except ValidationError as exc:
        messages.error(request, str(exc.messages[0]))
        return redirect(page.get_absolute_url())

    order = (request.POST.get("order") or "").strip()
    if order.isdigit():
        page.order = int(order)
    page.updated_by = request.user
    page.save()
    messages.success(
        request,
        f"“{page.title}” moved to the top level."
        if parent is None
        else f"“{page.title}” moved under “{parent.title}”.",
    )
    return redirect(page.get_absolute_url())


@login_required
def page_delete(request, slug):
    _staff_or_403(request)
    if not _is_admin(request):
        raise PermissionDenied
    page = get_object_or_404(Page.objects.select_related("space"), slug=slug)
    if request.method == "POST":
        space_slug = page.space.slug
        title = page.title
        page.delete()
        messages.success(request, f"Page “{title}” deleted.")
        return redirect("wiki:space_detail", slug=space_slug)
    return render(
        request,
        "wiki/page_confirm_delete.html",
        {"page": page, "descendant_count": len(page.descendant_ids())},
    )


@login_required
def preview(request):
    """The editor's live preview, through the renderer the saved page uses."""
    _staff_or_403(request)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        payload = json.loads(request.body.decode("utf-8") or "")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Send JSON with a body to preview."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Send JSON with a body to preview."}, status=400)

    body = payload.get("body", "")
    if not isinstance(body, str):
        return JsonResponse({"error": "The body must be text."}, status=400)
    if len(body) > MAX_BODY:
        return JsonResponse({"error": "That page is too long to preview."}, status=413)

    return JsonResponse({"html": render_markdown(body, user=request.user)})


@login_required
def page_attach(request, slug):
    """Attach uploaded files to a page and hand back their Markdown."""
    _staff_or_403(request)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    page = get_object_or_404(Page.objects.select_related("space"), slug=slug)

    # Nothing is saved unless every file fits: half an upload is worse than none.
    limit = _max_attachment_size()
    files = [f for f in request.FILES.getlist("files") if f]
    for f in files:
        if f.size and f.size > limit:
            return JsonResponse({"error": f"{f.name} is too large"}, status=400)

    created = [
        PageAttachment.objects.create(
            page=page,
            file=f,
            original_name=f.name[:255],
            content_type=getattr(f, "content_type", "") or "",
            size=f.size or 0,
            uploaded_by=request.user,
        )
        for f in files
    ]
    return JsonResponse({"files": [_attachment_json(a) for a in created]})


@login_required
def attachment_download(request, pk):
    """The file itself: images inline so previews can point at them here."""
    _staff_or_403(request)
    attachment = get_object_or_404(PageAttachment, pk=pk)
    inline = attachment.content_type.startswith("image/")
    try:
        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=not inline,
            filename=attachment.original_name,
        )
    except FileNotFoundError as exc:
        raise Http404 from exc


def _attachment_json(attachment):
    url = reverse("wiki:attachment_download", args=[attachment.pk])
    name = attachment.original_name
    if attachment.content_type.startswith("image/"):
        # Alt text becomes an HTML attribute, so it is escaped before Markdown is.
        markdown = f"![{escape(name)}]({url})"
    else:
        markdown = f"[{name}]({url})"
    return {"name": name, "url": url, "markdown": markdown}

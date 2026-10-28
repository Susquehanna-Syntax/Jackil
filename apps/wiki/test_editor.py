"""The editor's live preview endpoint, page attachments, and the editor script."""

import base64
import json
import re
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.wiki.markdown import render
from apps.wiki.models import Page, PageAttachment, Space

#: A real 1x1 PNG: a "PNG" that only looks like one would not be an image to
#: anything downstream that decodes the stored file.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)

# Uploads land in a throwaway directory, never the repo's media/; .rexymcp/ is gitignored.
_temp_media = override_settings(MEDIA_ROOT=Path(settings.BASE_DIR) / ".rexymcp" / "test-media")


def _png(name="screenshot.png"):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


class PreviewEndpointTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.customer = User.objects.create_user("cust1", password="x", role="customer")

    def preview(self, payload, user=None):
        self.client.force_login(user or self.agent)
        body = payload if isinstance(payload, str) else json.dumps(payload)
        return self.client.post(reverse("wiki:preview"), data=body, content_type="application/json")

    def test_preview_returns_sanitised_html(self):
        response = self.preview({"body": "# Title\n\n<script>alert(1)</script>$x$\n"})
        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        self.assertIn("<h1>Title</h1>", html)
        self.assertNotIn("<script", html)
        self.assertIn("math inline", html)

    def test_preview_over_1mb_is_413(self):
        response = self.preview({"body": "x" * 1_000_001})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"], "That page is too long to preview.")

    def test_preview_of_exactly_1mb_is_rendered(self):
        response = self.preview({"body": "x" * 1_000_000})
        self.assertEqual(response.status_code, 200)
        self.assertIn("<p>", response.json()["html"])

    def test_preview_of_a_body_that_is_not_text_is_400(self):
        response = self.preview({"body": ["not", "text"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "The body must be text.")

    def test_preview_bad_json_is_400(self):
        response = self.preview("<h1>not json</h1>")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Send JSON with a body to preview.")

    def test_preview_of_no_body_is_empty_html(self):
        response = self.preview({})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["html"], "")

    def test_preview_customer_403(self):
        response = self.preview({"body": "hi"}, user=self.customer)
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_sent_to_sign_in(self):
        response = self.client.post(
            reverse("wiki:preview"),
            data=json.dumps({"body": "hi"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)


@_temp_media
class AttachmentUploadTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.customer = User.objects.create_user("cust1", password="x", role="customer")
        cls.space = Space.objects.create(name="Ops")
        cls.page = Page.objects.create(space=cls.space, title="Runbook", body="steps")

    def upload(self, *files, user=None):
        self.client.force_login(user or self.agent)
        # A dict of lists posts several files under one "files" field; the test
        # client's multipart encoder accepts that shape and not a list of pairs.
        return self.client.post(
            reverse("wiki:page_attach", args=[self.page.slug]), {"files": list(files)}
        )

    def test_attach_image_and_file_return_markdown(self):
        response = self.upload(_png("diagram.png"), SimpleUploadedFile("notes.txt", b"hi"))
        self.assertEqual(response.status_code, 200)
        image, document = response.json()["files"]

        self.assertEqual(image["name"], "diagram.png")
        self.assertTrue(image["url"].startswith("/wiki/attachment/"))
        self.assertEqual(image["markdown"], f"![diagram.png]({image['url']})")

        self.assertEqual(document["name"], "notes.txt")
        self.assertEqual(document["markdown"], f"[notes.txt]({document['url']})")

        self.assertEqual(PageAttachment.objects.count(), 2)
        saved = PageAttachment.objects.get(original_name="diagram.png")
        self.assertEqual(saved.page_id, self.page.pk)
        self.assertEqual(saved.uploaded_by_id, self.agent.pk)
        self.assertEqual(saved.content_type, "image/png")
        self.assertEqual(saved.size, len(PNG))

    @override_settings(MAX_ATTACHMENT_SIZE=10)
    def test_attachment_too_large_is_refused_and_nothing_saved(self):
        response = self.upload(SimpleUploadedFile("notes.txt", b"x" * 20))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "notes.txt is too large")
        self.assertEqual(PageAttachment.objects.count(), 0)

    @override_settings(MAX_ATTACHMENT_SIZE=10)
    def test_one_oversize_file_refuses_the_whole_upload(self):
        response = self.upload(_png("small.png"), SimpleUploadedFile("big.txt", b"x" * 20))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PageAttachment.objects.count(), 0)

    def test_upload_of_nothing_is_empty(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["files"], [])

    def test_upload_customer_403_and_no_rows(self):
        response = self.upload(_png(), user=self.customer)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(PageAttachment.objects.count(), 0)


@_temp_media
class AttachmentDownloadTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.customer = User.objects.create_user("cust1", password="x", role="customer")
        cls.space = Space.objects.create(name="Ops")
        cls.page = Page.objects.create(space=cls.space, title="Runbook")

    def attach(self, name="diagram.png", content_type="image/png"):
        return PageAttachment.objects.create(
            page=self.page,
            file=SimpleUploadedFile(name, PNG, content_type=content_type),
            original_name=name,
            content_type=content_type,
            size=len(PNG),
        )

    def test_agent_downloads_the_bytes_under_the_original_name(self):
        attachment = self.attach()
        self.client.force_login(self.agent)
        response = self.client.get(reverse("wiki:attachment_download", args=[attachment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("diagram.png", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), PNG)

    def test_images_render_inline_and_other_files_download(self):
        self.client.force_login(self.agent)
        image = self.attach()
        document = self.attach("notes.txt", "text/plain")

        self.assertNotIn(
            "attachment",
            self.client.get(reverse("wiki:attachment_download", args=[image.pk]))[
                "Content-Disposition"
            ],
        )
        self.assertIn(
            "attachment",
            self.client.get(reverse("wiki:attachment_download", args=[document.pk]))[
                "Content-Disposition"
            ],
        )

    def test_attachment_download_for_staff_and_403_for_customer(self):
        attachment = self.attach()
        url = reverse("wiki:attachment_download", args=[attachment.pk])

        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(url).status_code, 403)


class RelativeImageUrlTest(TestCase):
    def test_relative_image_url_survives_the_sanitiser(self):
        agent = User.objects.create_user("agent1", password="x", role="agent")
        html = str(render("![a](/wiki/attachment/3/)", user=agent))
        self.assertIn('src="/wiki/attachment/3/"', html)


class EditorPageTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("agent1", password="x", role="agent")
        cls.space = Space.objects.create(name="Ops")
        cls.page = Page.objects.create(space=cls.space, title="Runbook", body="steps")

    def test_editor_page_loads_the_editor_script_and_toolbar(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("wiki:page_edit", args=[self.page.slug]))
        self.assertContains(response, "js/jackil-wiki-editor.js")
        self.assertContains(response, 'class="wiki-toolbar"')
        self.assertContains(response, "data-wiki-editor")
        self.assertContains(response, "data-wiki-attach")
        self.assertContains(response, f'data-attach-url="/wiki/p/{self.page.slug}/attach/"')

    def test_new_page_attach_button_is_disabled(self):
        self.client.force_login(self.agent)
        body = self.client.get(reverse("wiki:page_new")).content.decode()
        self.assertIn("js/jackil-wiki-editor.js", body)
        self.assertNotIn("data-attach-url", body)


class EditorScriptTests(SimpleTestCase):
    """The script's own contract, checked against its source.

    The toolbar is built by script, so a click handler that looks a button up by
    attribute can be dead while every server-side test still passes: what is
    asserted here are the attributes the rendered markup has to carry, and the
    one payload form that cannot survive being written into an HTML attribute.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = (Path(settings.BASE_DIR) / "static/js/jackil-wiki-editor.js").read_text()
        start = cls.source.index("const WIKI_BUTTONS = [")
        cls.specs = re.findall(r"^\s*\['([^']*)', '([^']*)', '(.*)'\],$", cls.source[start:], re.M)

    def test_script_calls_the_preview_endpoint_and_handles_paste_and_drop(self):
        for literal in [
            "/wiki/preview/",
            "beforeunload",
            "insertAround",
            "clipboardData",
            "dataTransfer",
            "X-CSRFToken",
        ]:
            self.assertIn(literal, self.source)

    def test_rendered_toolbar_buttons_carry_the_attributes_the_handler_reads(self):
        # The handler finds its button with closest('[data-wiki-md]') and reads the
        # payload back off data-wiki-insert. Markup missing either renders a
        # toolbar of buttons that do nothing at all when clicked.
        self.assertIn("closest('[data-wiki-md]')", self.source)
        self.assertIn("getAttribute('data-wiki-insert')", self.source)
        rendered = "".join(
            f'<button type="button" data-wiki-md="{name}" data-wiki-insert="{insert}" '
            f'title="{label}" aria-label="{label}">{label}</button>'
            for label, name, insert in self.specs
        )
        for attribute in ["type=", "data-wiki-md=", "data-wiki-insert=", "title=", "aria-label="]:
            self.assertEqual(rendered.count(attribute), len(self.specs))

    def test_the_script_writes_those_attributes_from_the_button_table(self):
        # The check above is only as honest as this: the markup it counts has to be
        # the markup wikiToolbarMarkup actually emits.
        generator = self.source[self.source.index("function wikiToolbarMarkup") :]
        for attribute in ["data-wiki-md=", "data-wiki-insert=", 'title="', 'aria-label="']:
            self.assertIn(attribute, generator)
        self.assertIn('type="button"', generator)

    def test_no_toolbar_payload_could_be_read_as_the_wrong_kind(self):
        # "wrap:" is the only payload kind split on "|", and a bare "|" is a
        # Markdown cell delimiter: Page link's "[[|]]" needs it as its separator
        # and Table carries pipes in text that must not be wrapped at all. A wrap
        # with an unescaped second "|" would hand insertAround half of each.
        self.assertEqual(len(self.specs), 10)
        for label, _, spec in self.specs:
            if spec.startswith("wrap:"):
                body = spec[len("wrap:") :]
                self.assertEqual(body.count("|"), 1, f"{label}: {spec!r} is ambiguous")
            elif "|" in spec and "\\n" not in spec:
                self.fail(f"{label}: a bare | in {spec!r} would be read as a wrap split")

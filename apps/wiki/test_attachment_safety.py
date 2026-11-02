"""Attachments are only ever shown inline when their bytes are a raster image."""

import io
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.wiki.models import Page, PageAttachment, Space

_MEDIA = tempfile.mkdtemp()


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format="PNG")
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=_MEDIA)
class AttachmentSafetyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create_user("att-agent", "aa@x.com", "pw", role="agent")
        space = Space.objects.create(name="Att")
        cls.page = Page.objects.create(space=space, title="Att page")

    def setUp(self):
        self.client.force_login(self.agent)

    def _upload(self, name, data, content_type):
        url = reverse("wiki:page_attach", args=[self.page.slug])
        resp = self.client.post(url, {"files": SimpleUploadedFile(name, data, content_type)})
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()["files"][0]

    def _get(self, info):
        return self.client.get(info["url"])

    def test_a_real_png_is_served_inline_as_png(self):
        info = self._upload("dot.png", _png_bytes(), "image/png")
        self.assertTrue(info["markdown"].startswith("!["))
        resp = self._get(info)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertNotIn("attachment", resp.get("Content-Disposition", ""))

    def test_html_claiming_to_be_a_png_is_a_download(self):
        info = self._upload("x.html", b"<script>alert(1)</script>", "image/png")
        self.assertFalse(info["markdown"].startswith("!["))
        resp = self._get(info)
        self.assertEqual(resp["Content-Type"], "application/octet-stream")
        self.assertIn("attachment", resp["Content-Disposition"])

    def test_svg_is_never_inline(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        info = self._upload("logo.svg", svg, "image/svg+xml")
        resp = self._get(info)
        self.assertEqual(resp["Content-Type"], "application/octet-stream")
        self.assertIn("attachment", resp["Content-Disposition"])

    def test_a_stored_image_type_on_a_non_image_is_not_trusted(self):
        info = self._upload("notes.txt", b"plain words", "text/plain")
        PageAttachment.objects.update(content_type="image/png")  # a row edited by hand
        resp = self._get(info)
        self.assertEqual(resp["Content-Type"], "application/octet-stream")

    def test_every_attachment_response_is_sandboxed_and_nosniff(self):
        for name, data, ctype in (
            ("dot.png", _png_bytes(), "image/png"),
            ("notes.txt", b"words", "text/plain"),
        ):
            with self.subTest(name=name):
                resp = self._get(self._upload(name, data, ctype))
                self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
                self.assertIn("sandbox", resp["Content-Security-Policy"])

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

PASTELS = "rose|lavender|mint|peach|sky|lemon|coral"


def _template_files():
    root = Path(settings.BASE_DIR)
    files = list((root / "templates").rglob("*.html"))
    for app_dir in sorted((root / "apps").glob("*/templates")):
        files.extend(app_dir.rglob("*.html"))
    return files


class PaperSafetyTests(SimpleTestCase):
    """Pastel text and thin lines must use the -ink tokens so they stay
    legible on Paper's cream ground; the design is flat."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (Path(settings.BASE_DIR) / "static/css/style.css").read_text()

    def test_css_text_colours_use_ink(self):
        hits = re.findall(rf"(?<![-\w])color:\s*var\(--({PASTELS})\)", self.css)
        self.assertEqual(hits, [])

    def test_css_lines_use_ink(self):
        hits = re.findall(rf"(stroke|border-color):\s*var\(--({PASTELS})\)", self.css)
        self.assertEqual(hits, [])

    def test_templates_inline_colours_use_ink(self):
        pattern = re.compile(rf"(?<![-\w])color:\s*var\(--({PASTELS}|bg)\)")
        offenders = [str(p) for p in _template_files() if pattern.search(p.read_text())]
        self.assertEqual(offenders, [])

    def test_flat_design(self):
        self.assertNotIn("linear-gradient(", self.css)
        self.assertNotIn("radial-gradient(", self.css)

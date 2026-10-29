from pathlib import Path

from django.test import SimpleTestCase

STATIC = Path(__file__).resolve().parents[2] / "static" / "css"
TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / "wiki"

# Every short class name Pygments' HtmlFormatter emits, except `w` (whitespace).
PYGMENTS_CLASSES = [
    "bp",
    "c",
    "c1",
    "ch",
    "cm",
    "cp",
    "cpf",
    "cs",
    "dl",
    "err",
    "fm",
    "g",
    "gd",
    "ge",
    "ges",
    "gh",
    "gi",
    "go",
    "gp",
    "gr",
    "gs",
    "gt",
    "gu",
    "il",
    "k",
    "kc",
    "kd",
    "kn",
    "kp",
    "kr",
    "kt",
    "l",
    "ld",
    "m",
    "mb",
    "mf",
    "mh",
    "mi",
    "mo",
    "n",
    "na",
    "nb",
    "nc",
    "nd",
    "ne",
    "nf",
    "ni",
    "nl",
    "nn",
    "no",
    "nt",
    "nv",
    "nx",
    "o",
    "ow",
    "p",
    "pm",
    "py",
    "s",
    "s1",
    "s2",
    "sa",
    "sb",
    "sc",
    "sd",
    "se",
    "sh",
    "si",
    "sr",
    "ss",
    "sx",
    "vc",
    "vg",
    "vi",
    "vm",
    "x",
]


class CodeCssTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.code_css = (STATIC / "code.css").read_text()

    def test_every_pygments_class_is_coloured(self):
        joined = f" {self.code_css} "
        for cls in PYGMENTS_CLASSES:
            with self.subTest(cls=cls):
                self.assertIn(f".markdown-body .{cls}", joined)

    def test_only_design_tokens(self):
        self.assertNotIn("#", self.code_css)
        for i, line in enumerate(self.code_css.splitlines(), 1):
            start = 0
            while True:
                j = line.find("rgb(", start)
                if j < 0:
                    break
                with self.subTest(line=i):
                    self.assertTrue(line[j:].startswith("rgba(var("), f"non-token colour: {line}")
                start = j + 4

    def test_old_block_removed_from_style_css(self):
        style = (STATIC / "style.css").read_text()
        self.assertNotIn("Pygments token colours", style)

    def test_wiki_pages_load_code_css(self):
        for name in ("page_detail.html", "page_form.html"):
            with self.subTest(template=name):
                self.assertIn("css/code.css", (TEMPLATES / name).read_text())

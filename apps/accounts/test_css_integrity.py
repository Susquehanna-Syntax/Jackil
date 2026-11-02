import re

from django.conf import settings
from django.test import SimpleTestCase


class StylesheetIntegrityTests(SimpleTestCase):
    """A comment left open swallows every rule after it until the next `*/`.

    Two truncated comments copied in from Vigil's stylesheet once hid the
    add-widget rail's positioning and the dashboard card styles, and nothing
    else noticed: the CSS still parsed, it just had fewer rules.
    """

    def setUp(self):
        self.css = (settings.BASE_DIR / "static/css/style.css").read_text()

    def test_no_comment_swallows_another(self):
        for m in re.finditer(r"/\*", self.css):
            end = self.css.find("*/", m.start() + 2)
            self.assertNotEqual(end, -1, "a comment is never closed")
            nested = self.css.find("/*", m.start() + 2)
            line = self.css[: m.start()].count("\n") + 1
            self.assertFalse(
                -1 < nested < end, f"the comment opening on line {line} runs into another"
            )

    def test_braces_balance(self):
        stripped = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S)
        self.assertEqual(stripped.count("{"), stripped.count("}"))


class NoSideStripeTests(SimpleTestCase):
    """Hard rule: no coloured line down one side of anything, anywhere.

    Colour a card, row or message fully (a tint and/or a full border) or not
    at all. A neutral 1px divider on a panel's edge (the sidebar, the rail)
    is the only one-sided border allowed.
    """

    NEUTRAL = ("var(--border)", "var(--glass-edge)", "var(--s3)", "transparent", "none")

    def _css_files(self):
        root = settings.BASE_DIR / "static" / "css"
        return [p for p in root.glob("*.css")]

    def test_no_coloured_side_border(self):
        side = re.compile(
            r"border-(?:left|right|inline-start|inline-end)(?P<prop>-color|-width)?\s*:\s*(?P<value>[^;}]+)"
        )
        for path in self._css_files():
            text = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
            for m in side.finditer(text):
                value = m["value"].strip()
                line = text[: m.start()].count("\n") + 1
                with self.subTest(file=path.name, line=line, rule=m.group(0)):
                    self.assertNotEqual(
                        m["prop"], "-color", "a side-only border colour is a stripe"
                    )
                    if m["prop"] == "-width":
                        continue
                    if value.startswith("0") or value in ("none", "0"):
                        continue
                    self.assertTrue(
                        any(n in value for n in self.NEUTRAL)
                        and "px" in value
                        and not re.search(r"\b([2-9]|\d{2,})px", value),
                        "only a neutral 1px edge may sit on one side",
                    )

    def test_no_inset_side_shadow(self):
        stripe = re.compile(r"box-shadow\s*:[^;}]*inset\s+-?[1-9]\d*px\s+0(?:px)?\s+0")
        for path in self._css_files():
            text = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
            self.assertIsNone(stripe.search(text), f"{path.name} has an inset side shadow")

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

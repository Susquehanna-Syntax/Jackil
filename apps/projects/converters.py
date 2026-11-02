"""Path converters that keep ``NET`` and ``NET-12`` two different URLs."""

import re


class ProjectKeyConverter:
    """``NET`` — a project key, never a whole issue reference."""

    regex = "[A-Za-z][A-Za-z0-9]{1,9}"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


class IssueRefConverter:
    """``NET-12`` as ``(NET, 12)``."""

    regex = "[A-Za-z][A-Za-z0-9]{1,9}-[0-9]+"
    _SPLIT = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9]{1,9})-(?P<number>[0-9]+)$")

    def to_python(self, value):
        match = self._SPLIT.match(value)
        if match is None:
            raise ValueError(value)
        return match.group("key").upper(), int(match.group("number"))

    def to_url(self, value):
        if isinstance(value, tuple | list):
            return f"{value[0]}-{value[1]}"
        return value

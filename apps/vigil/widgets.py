"""Vigil's widget catalogue, shown and drawn as if it were Jackil's own.

Kinds are namespaced ``vigil:<kind>`` so a saved layout can never collide with
a Jackil registry key, and so the dashboards views can tell a remote kind from
a local one without importing Vigil eagerly. When Vigil cannot be read nothing
here raises: every failure becomes a stat tile that says so in words, and
``DOWN_KEY`` keeps us from calling a dead Vigil once per widget per refresh.
"""

import re

from django.core.cache import cache
from django.core.exceptions import PermissionDenied

from apps.dashboards.contract import SHAPES
from apps.vigil.client import VigilUnavailable, get_client
from apps.vigil.links import DOWN_KEY, DOWN_SECONDS

PREFIX = "vigil:"
CATALOG_KEY = "vigil:catalog"
CATALOG_SECONDS = 300
KIND_RE = re.compile(r"^vigil:[a-z][a-z0-9_]{0,39}$")


def is_remote(kind) -> bool:
    return bool(KIND_RE.match(str(kind)))


def _client():
    if cache.get(DOWN_KEY):
        return None
    return get_client()


def _convert_setting(spec: dict) -> dict | None:
    kind = spec.get("type")
    if kind == "choice":
        pairs = []
        for choice in spec.get("choices") or []:
            if not isinstance(choice, (list, tuple)) or len(choice) != 2:
                continue
            value, label = choice
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                continue
            pairs.append([str(value), str(label)])
        return {
            "type": "choice",
            "label": str(spec.get("label") or "Choice"),
            "default": str(spec.get("default") or (pairs[0][0] if pairs else "")),
            "options": pairs,
        }
    if kind == "int":
        return {
            "type": "int",
            "label": str(spec.get("label") or "Number"),
            "default": spec.get("default") if isinstance(spec.get("default"), int) else 1,
            "min": spec.get("min") if isinstance(spec.get("min"), int) else 1,
            "max": spec.get("max") if isinstance(spec.get("max"), int) else 50,
        }
    return None


def _entry(spec: dict) -> dict | None:
    kind = str(spec.get("kind") or "")
    shape = str(spec.get("shape") or "")
    if not KIND_RE.match(f"{PREFIX}{kind}") or shape not in SHAPES:
        return None
    small = shape in ("stat", "gauge")
    settings = {}
    for name, field in (spec.get("settings") or {}).items():
        if not isinstance(field, dict):
            continue
        converted = _convert_setting(field)
        if converted is not None:
            settings[str(name)] = converted
    return {
        "group": "vigil",
        "shape": shape,
        "label": str(spec.get("title") or kind),
        "description": str(spec.get("description") or ""),
        "w": 3 if small else 6,
        "h": 2 if small else 4,
        "min_w": 2 if small else 3,
        "min_h": 2 if small else 3,
        "settings": settings,
    }


def remote_catalog() -> dict[str, dict]:
    """Vigil's widgets as dashboards registry entries, keyed ``vigil:<kind>``.

    Empty when Vigil is not connected or was recently unreachable — the rail
    then simply has no Vigil group.
    """
    client = _client()
    if client is None:
        return {}
    catalog = cache.get(CATALOG_KEY)
    if catalog is not None:
        return catalog
    try:
        specs = client.widgets()
    except VigilUnavailable as exc:
        cache.set(DOWN_KEY, str(exc), DOWN_SECONDS)
        return {}
    catalog = {}
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        entry = _entry(spec)
        if entry is not None:
            catalog[f"{PREFIX}{spec['kind']}"] = entry
    cache.set(CATALOG_KEY, catalog, CATALOG_SECONDS)
    return catalog


def _message(label: str) -> dict:
    return {
        "version": 1,
        "shape": "stat",
        "data": {"value": 0, "label": label, "tone": "muted"},
    }


def _params(entry: dict | None, raw_settings: dict) -> dict:
    """Only settings the catalog entry declares, each within its own bounds."""
    params: dict = {}
    if not entry:
        return params
    for name, field in entry["settings"].items():
        if name not in raw_settings:
            continue
        value = raw_settings[name]
        if field["type"] == "choice":
            options = [value for value, _label in field["options"]]
            params[name] = value if value in options else field["default"]
        elif field["type"] == "int":
            try:
                number = int(value)
            except (TypeError, ValueError):
                number = field["default"]
            params[name] = max(field["min"], min(number, field["max"]))
    return params


def remote_widget_data(kind: str, raw_settings: dict, user) -> dict:
    """One Vigil widget's data, always as a valid envelope."""
    if getattr(user, "role", "") not in ("agent", "admin"):
        raise PermissionDenied("only agents may read Vigil widgets")
    if not isinstance(raw_settings, dict):
        raw_settings = {}
    client = get_client()
    if client is None:
        return _message("Vigil is not connected.")
    if cache.get(DOWN_KEY):
        return _message("Vigil unavailable")
    catalog = remote_catalog()
    params = _params(catalog.get(kind), raw_settings)
    try:
        payload = client.widget(str(kind)[len(PREFIX) :], params)
    except VigilUnavailable as exc:
        cache.set(DOWN_KEY, str(exc), DOWN_SECONDS)
        return _message("Vigil unavailable")
    if payload is None:
        return _message("This Vigil widget no longer exists.")
    shape = payload.get("shape") if isinstance(payload, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else None
    if shape not in SHAPES or not isinstance(data, dict):
        return _message("Vigil sent a widget Jackil could not draw.")
    from apps.dashboards.contract import validate_payload

    try:
        validate_payload(shape, data)
    except ValueError:
        return _message("Vigil sent a widget Jackil could not draw.")
    return {"version": 1, "shape": shape, "data": data}

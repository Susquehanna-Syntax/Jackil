"""The widget data contract: what every widget's payload must look like.

Every widget, Jackil's own or one streamed from a sibling app in M6, returns
a versioned envelope::

    {"version": 1, "shape": "stat", "data": {...}}

``validate_payload`` is the single definition of each shape, so a broken
widget fails where it is written rather than rendering as garbage. A payload
that refuses to validate is a bug in the widget, not user input — hence
``ValueError`` and not an HTTP error.
"""

WIDGET_SCHEMA_VERSION = 1
SHAPES = ("stat", "list", "table", "gauge", "series")
TONES = ("ok", "warn", "bad", "info", "muted")
SERIES_KINDS = ("bar", "line", "area", "stacked-bar")


def _is_number(value) -> bool:
    """int or float, and never ``bool`` — which is an int in Python."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_str(data: dict, key: str, where: str) -> None:
    if key not in data:
        raise ValueError(f"{where}: {key!r} is required")
    if not isinstance(data[key], str):
        raise ValueError(f"{where}: {key!r} must be a string, got {type(data[key]).__name__}")


def _optional_str(data: dict, key: str, where: str) -> None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{where}: {key!r} must be a string or absent")


def _optional_tone(data: dict, where: str) -> None:
    tone = data.get("tone")
    if tone is not None and tone not in TONES:
        raise ValueError(f"{where}: tone {tone!r} is not one of {'/'.join(TONES)}")


def _check_stat(data: dict) -> None:
    where = "stat"
    if "value" not in data:
        raise ValueError(f"{where}: 'value' is required")
    if not _is_number(data["value"]):
        raise ValueError(f"{where}: 'value' must be a number, got {type(data['value']).__name__}")
    _require_str(data, "label", where)
    _optional_tone(data, where)
    _optional_str(data, "href", where)
    _optional_str(data, "sub", where)
    for key in data:
        if key not in ("value", "label", "tone", "href", "sub"):
            raise ValueError(f"{where}: unknown key {key!r}")


def _check_list(data: dict) -> None:
    where = "list"
    if "items" not in data:
        raise ValueError(f"{where}: 'items' is required")
    items = data["items"]
    if not isinstance(items, list):
        raise ValueError(f"{where}: 'items' must be a list")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{where}: item {i} must be an object")
        _require_str(item, "title", f"{where}: item {i}")
        for key in ("href", "meta", "badge"):
            _optional_str(item, key, f"{where}: item {i}")
        _optional_tone(item, f"{where}: item {i}")
        for key in item:
            if key not in ("title", "href", "meta", "badge", "tone"):
                raise ValueError(f"{where}: item {i} has unknown key {key!r}")
    _require_str(data, "empty", where)
    for key in data:
        if key not in ("items", "empty"):
            raise ValueError(f"{where}: unknown key {key!r}")


def _check_table(data: dict) -> None:
    where = "table"
    if "columns" not in data:
        raise ValueError(f"{where}: 'columns' is required")
    columns = data["columns"]
    if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
        raise ValueError(f"{where}: 'columns' must be a list of strings")
    if "rows" not in data:
        raise ValueError(f"{where}: 'rows' is required")
    rows = data["rows"]
    if not isinstance(rows, list):
        raise ValueError(f"{where}: 'rows' must be a list")
    for i, row in enumerate(rows):
        if not isinstance(row, list):
            raise ValueError(f"{where}: row {i} must be a list")
        if len(row) != len(columns):
            raise ValueError(
                f"{where}: row {i} has {len(row)} cells, expected {len(columns)} (one per column)"
            )
        for j, cell in enumerate(row):
            if not isinstance(cell, (str, int, float)) or isinstance(cell, bool):
                raise ValueError(
                    f"{where}: row {i} cell {j} must be a string or number, "
                    f"got {type(cell).__name__}"
                )
    for key in data:
        if key not in ("columns", "rows"):
            raise ValueError(f"{where}: unknown key {key!r}")


def _check_gauge(data: dict) -> None:
    where = "gauge"
    if "value" not in data:
        raise ValueError(f"{where}: 'value' is required")
    value = data["value"]
    # None is a real answer: there was nothing to measure.
    if value is not None:
        if not _is_number(value):
            raise ValueError(f"{where}: 'value' must be a number or None")
        if not 0 <= value <= 100:
            raise ValueError(f"{where}: 'value' must be between 0 and 100, got {value}")
    _require_str(data, "label", where)
    _optional_tone(data, where)
    _optional_str(data, "sub", where)
    for key in data:
        if key not in ("value", "label", "tone", "sub"):
            raise ValueError(f"{where}: unknown key {key!r}")


def _check_series(data: dict) -> None:
    where = "series"
    if "kind" not in data:
        raise ValueError(f"{where}: 'kind' is required")
    kind = data["kind"]
    if kind not in SERIES_KINDS:
        raise ValueError(f"{where}: kind {kind!r} is not one of {'/'.join(SERIES_KINDS)}")
    if "labels" not in data:
        raise ValueError(f"{where}: 'labels' is required")
    labels = data["labels"]
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise ValueError(f"{where}: 'labels' must be a list of strings")
    if "series" not in data:
        raise ValueError(f"{where}: 'series' is required")
    series = data["series"]
    if not isinstance(series, list):
        raise ValueError(f"{where}: 'series' must be a list")
    for i, s in enumerate(series):
        point = f"{where}: series {i}"
        if not isinstance(s, dict):
            raise ValueError(f"{point} must be an object")
        _require_str(s, "name", point)
        if "values" not in s:
            raise ValueError(f"{point}: 'values' is required")
        values = s["values"]
        if not isinstance(values, list) or not all(_is_number(v) for v in values):
            raise ValueError(f"{point}: 'values' must be a list of numbers")
        if len(values) != len(labels):
            raise ValueError(f"{point}: {len(values)} values for {len(labels)} labels")
        for key in s:
            if key not in ("name", "values"):
                raise ValueError(f"{point}: unknown key {key!r}")
    for key in data:
        if key not in ("kind", "labels", "series"):
            raise ValueError(f"{where}: unknown key {key!r}")


_CHECKS = {
    "stat": _check_stat,
    "list": _check_list,
    "table": _check_table,
    "gauge": _check_gauge,
    "series": _check_series,
}


def validate_payload(shape: str, data: dict) -> None:
    """Raise ``ValueError`` unless *data* is a valid payload for *shape*."""
    if shape not in SHAPES:
        raise ValueError(f"unknown shape {shape!r}")
    if not isinstance(data, dict):
        raise ValueError(f"{shape}: data must be an object")
    _CHECKS[shape](data)


def envelope(shape: str, data: dict) -> dict:
    """Validate *data* and wrap it in the versioned envelope."""
    validate_payload(shape, data)
    return {"version": WIDGET_SCHEMA_VERSION, "shape": shape, "data": data}

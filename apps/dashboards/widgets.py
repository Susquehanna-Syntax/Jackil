"""What a widget may be.

One registry, read by the API, so the catalog and the per-widget settings form
are generated rather than hand-maintained in two places. Sizes are Gridstack
grid units on a 12-column grid.

``group`` places a widget in the Add-widget rail: tickets, sla, work, people.
``shape`` is the phase-02 data contract's rendering shape: stat, list, table,
gauge, series.

Setting types the form generator knows how to render: ``choice`` — one of
`options`; ``int`` — a bounded number; ``text`` — a short string; ``bool`` —
a checkbox; ``saved_view`` — an int chosen from the operator's saved views, 0
meaning "all open tickets"; ``project`` — a project key chosen from the
non-archived projects, "" meaning "none picked yet"; ``report_card`` — a
``"<report uuid>:<card index>"`` chosen from the reports the operator can
see, "" meaning "none picked yet". A type no field in the registry uses yet
stays out of the form generator: it would be rendering for a caller that does
not exist.
"""

WIDGET_REGISTRY: dict[str, dict] = {
    "stat_tile": {
        "group": "tickets",
        "shape": "stat",
        "label": "Stat tile",
        "description": "One number: open, unassigned, overdue, breached, critical, or created/resolved this week.",
        "w": 3,
        "h": 2,
        "min_w": 2,
        "min_h": 2,
        "settings": {
            "stat": {
                "type": "choice",
                "label": "Which number",
                "options": [
                    "open",
                    "unassigned",
                    "overdue",
                    "breached",
                    "critical",
                    "created_week",
                    "resolved_week",
                ],
                "default": "open",
            },
        },
    },
    "ticket_list": {
        "group": "tickets",
        "shape": "list",
        "label": "Ticket list",
        "description": "Tickets from a saved view, newest first.",
        "w": 6,
        "h": 4,
        "min_w": 3,
        "min_h": 3,
        "settings": {
            "saved_view": {"type": "saved_view", "label": "Saved view", "default": 0},
            "limit": {"type": "int", "label": "How many", "min": 1, "max": 50, "default": 10},
        },
    },
    "needs_attention": {
        "group": "sla",
        "shape": "list",
        "label": "Needs attention",
        "description": "Open tickets past or near their resolution due time.",
        "w": 6,
        "h": 5,
        "min_w": 3,
        "min_h": 3,
        "settings": {
            "limit": {"type": "int", "label": "How many", "min": 1, "max": 50, "default": 8},
        },
    },
    "my_work": {
        "group": "work",
        "shape": "list",
        "label": "My work",
        "description": "Open tickets assigned to you.",
        "w": 6,
        "h": 5,
        "min_w": 3,
        "min_h": 3,
        "settings": {
            "limit": {"type": "int", "label": "How many", "min": 1, "max": 50, "default": 8},
        },
    },
    "sla_compliance": {
        "group": "sla",
        "shape": "gauge",
        "label": "SLA compliance",
        "description": "Share of tickets resolved within their SLA.",
        "w": 3,
        "h": 4,
        "min_w": 2,
        "min_h": 3,
        "settings": {
            "range_days": {
                "type": "int",
                "label": "Days back",
                "min": 1,
                "max": 365,
                "default": 30,
            },
        },
    },
    "tickets_by_status": {
        "group": "tickets",
        "shape": "series",
        "label": "Tickets by status",
        "description": "How many tickets are in each status.",
        "w": 6,
        "h": 4,
        "min_w": 3,
        "min_h": 3,
        "settings": {},
    },
    "tickets_by_priority": {
        "group": "tickets",
        "shape": "series",
        "label": "Tickets by priority",
        "description": "Open tickets by priority.",
        "w": 6,
        "h": 4,
        "min_w": 3,
        "min_h": 3,
        "settings": {},
    },
    "volume_trend": {
        "group": "tickets",
        "shape": "series",
        "label": "Ticket volume",
        "description": "Tickets created and resolved per day.",
        "w": 6,
        "h": 4,
        "min_w": 4,
        "min_h": 3,
        "settings": {
            "range_days": {
                "type": "int",
                "label": "Days back",
                "min": 7,
                "max": 365,
                "default": 30,
            },
        },
    },
    "agent_load": {
        "group": "people",
        "shape": "table",
        "label": "Agent load",
        "description": "Open tickets per agent.",
        "w": 6,
        "h": 4,
        "min_w": 3,
        "min_h": 3,
        "settings": {},
    },
    "sprint_burndown": {
        "group": "projects",
        "shape": "series",
        "label": "Sprint burndown",
        "description": "Points left in a project's active sprint, day by day.",
        "w": 6,
        "h": 4,
        "min_w": 3,
        "min_h": 3,
        "settings": {
            "project": {"type": "project", "label": "Project", "default": ""},
        },
    },
    "team_load": {
        "group": "projects",
        "shape": "table",
        "label": "Team load",
        "description": "Story points committed this sprint against each person's usual.",
        "w": 6,
        "h": 4,
        "min_w": 3,
        "min_h": 3,
        "settings": {
            "project": {"type": "project", "label": "Project", "default": ""},
        },
    },
    "my_issues": {
        "group": "projects",
        "shape": "list",
        "label": "My issues",
        "description": "Open project issues assigned to you.",
        "w": 6,
        "h": 5,
        "min_w": 3,
        "min_h": 3,
        "settings": {
            "limit": {"type": "int", "label": "How many", "min": 1, "max": 50, "default": 8},
        },
    },
    "project_cost": {
        "group": "projects",
        "shape": "stat",
        "label": "Project cost",
        "description": "What a project's finished work cost.",
        "w": 3,
        "h": 2,
        "min_w": 2,
        "min_h": 2,
        "settings": {
            "project": {"type": "project", "label": "Project", "default": ""},
        },
    },
    # The registry's shape is the default only: the real one comes from the
    # report card's own envelope, which widget_data passes through untouched.
    "report_chart": {
        "group": "work",
        "shape": "series",
        "label": "Report chart",
        "description": "One card from a saved report.",
        "w": 6,
        "h": 4,
        "min_w": 3,
        "min_h": 3,
        "settings": {
            "card": {"type": "report_card", "label": "Report card", "default": ""},
        },
    },
}

SHAPES = ("stat", "list", "table", "gauge", "series")

GROUPS = ("tickets", "sla", "work", "people", "projects")

#: Settings every widget has, whatever its kind. The card title lives here
#: rather than in each of the nine entries: a dashboard may hold three ticket
#: lists, and "Ticket list" three times over names none of them.
UNIVERSAL_SETTINGS: dict[str, dict] = {
    "title": {
        "type": "text",
        "label": "Card title",
        "placeholder": "Leave blank to use the widget's own name",
        "default": "",
    },
}


def settings_for(kind: str) -> dict:
    """Every setting a widget of *kind* accepts, universal ones first."""
    spec = WIDGET_REGISTRY.get(kind) or {}
    return {**UNIVERSAL_SETTINGS, **(spec.get("settings") or {})}


#: Grid width every layout is expressed against.
GRID_COLUMNS = 12

#: How tall one widget may be. A separate number from the column count: rows
#: and columns are different axes, and a chart two screens tall is a layout
#: nobody can read rather than one worth storing.
GRID_MAX_ROWS = 24


def default_settings(kind: str) -> dict:
    """The settings a freshly added widget of *kind* starts with."""
    return {name: field.get("default") for name, field in settings_for(kind).items()}


def clean_settings(kind: str, raw) -> dict:
    """Keep only settings the registry declares for *kind*.

    A widget's settings are operator-supplied JSON. Storing unknown keys would
    let one widget's payload grow without bound and would leak whatever a
    client happened to send into every later read.
    """
    declared = settings_for(kind)
    if not isinstance(raw, dict):
        return default_settings(kind)
    cleaned = default_settings(kind)
    for name, value in raw.items():
        if name not in declared:
            continue
        field = declared[name]
        if field["type"] in ("int", "saved_view"):
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            lo, hi = field.get("min", 0), field.get("max")
            if lo is not None and value < lo:
                value = lo
            if hi is not None and value > hi:
                value = hi
        elif field["type"] == "choice":
            if value not in field.get("options", []):
                continue
        elif field["type"] == "bool":
            value = bool(value)
        elif field["type"] == "project":
            value = str(value).strip().upper()[:10]
        elif field["type"] == "report_card":
            value = str(value).strip()[:60]
        else:
            value = str(value)[:200]
        cleaned[name] = value
    return cleaned

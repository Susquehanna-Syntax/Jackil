"""The registry of report card kinds.

Each entry describes one card the builder can offer: what it shows, how the
number is worked out, which chart families it renders as, and its default
size on the report grid. ``QUERIES`` maps each kind to the function in
``apps.reports.queries`` that produces its data.
"""

from apps.reports import queries

GROUPS = ("tickets", "sla", "people", "projects", "wiki")

REPORT_WIDGETS: dict[str, dict] = {
    "ticket_volume": {
        "title": "Ticket volume",
        "description": ("Tickets created and resolved per day, over the report's range."),
        "chart": "line",
        "family": "days",
        "charts": ["line", "bar", "table"],
        "x_label": "Day",
        "y_label": "Tickets",
        "how": (
            "Tickets are counted on the day they were created. A ticket "
            "counts as resolved on the day it was closed."
        ),
        "size": {"w": 6, "h": 4},
        "group": "tickets",
    },
    "status_mix": {
        "title": "Status mix",
        "description": "How many tickets are in each status right now.",
        "chart": "bar",
        "family": "rows",
        "charts": ["bar", "table"],
        "x_label": "Status",
        "y_label": "Tickets",
        "how": (
            "Every ticket in the report's sources is counted once, under the status it holds now."
        ),
        "size": {"w": 4, "h": 4},
        "group": "tickets",
    },
    "priority_mix": {
        "title": "Priority mix",
        "description": "Open tickets by priority.",
        "chart": "bar",
        "family": "rows",
        "charts": ["bar", "table"],
        "x_label": "Priority",
        "y_label": "Open tickets",
        "how": (
            "Only open tickets are counted — every ticket that is not "
            "resolved or closed — under its current priority."
        ),
        "size": {"w": 4, "h": 4},
        "group": "tickets",
    },
    "sla_compliance": {
        "title": "SLA compliance",
        "description": ("Share of tickets closed each day that met their resolution deadline."),
        "chart": "line",
        "family": "days",
        "charts": ["line", "bar", "table"],
        "x_label": "Day",
        "y_label": "Within SLA (%)",
        "how": (
            "For each day, of the tickets with a resolution deadline that "
            "closed that day and are finished, the share closed on time. "
            "Days with no such tickets show 0."
        ),
        "size": {"w": 6, "h": 4},
        "group": "sla",
    },
    "first_response_time": {
        "title": "First response time",
        "description": ("Median hours from ticket creation to the first response, per day."),
        "chart": "line",
        "family": "days",
        "charts": ["line", "bar", "table"],
        "x_label": "Day",
        "y_label": "Hours",
        "how": (
            "Tickets are grouped by the day they were created. Each day "
            "shows the median hours to first response; tickets nobody has "
            "responded to are skipped."
        ),
        "size": {"w": 6, "h": 4},
        "group": "sla",
    },
    "resolution_time": {
        "title": "Resolution time",
        "description": ("Median hours from ticket creation to closure, per day of closure."),
        "chart": "line",
        "family": "days",
        "charts": ["line", "bar", "table"],
        "x_label": "Day",
        "y_label": "Hours",
        "how": (
            "Tickets are grouped by the day they were closed. Each day "
            "shows the median hours between creation and closure."
        ),
        "size": {"w": 6, "h": 4},
        "group": "sla",
    },
    "csat": {
        "title": "Satisfaction",
        "description": "Average satisfaction score per day of rating.",
        "chart": "line",
        "family": "days",
        "charts": ["line", "bar", "table"],
        "x_label": "Day",
        "y_label": "Average score",
        "how": (
            "Ratings are grouped by the day they were given. Each day shows "
            "the average score of the ratings filed that day."
        ),
        "size": {"w": 6, "h": 4},
        "group": "people",
    },
    "agent_load": {
        "title": "Agent load",
        "description": "Open tickets currently assigned to each agent.",
        "chart": "bar",
        "family": "rows",
        "charts": ["bar", "table"],
        "x_label": "Agent",
        "y_label": "Open tickets",
        "how": (
            "Every agent and admin is listed with the open tickets assigned "
            "to them now, most loaded first."
        ),
        "size": {"w": 4, "h": 4},
        "group": "people",
    },
}

QUERIES = {
    "ticket_volume": queries.ticket_volume,
    "status_mix": queries.status_mix,
    "priority_mix": queries.priority_mix,
    "sla_compliance": queries.sla_compliance,
    "first_response_time": queries.first_response_time,
    "resolution_time": queries.resolution_time,
    "csat": queries.csat,
    "agent_load": queries.agent_load,
}

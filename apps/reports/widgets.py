"""The registry of report card kinds.

Each entry describes one card the builder can offer: what it shows, how the
number is worked out, which chart families it renders as, and its default
size on the report grid. ``QUERIES`` maps each kind to the function in
``apps.reports.queries`` that produces its data; every query takes the
report's source (tickets, projects, or ``None`` for wiki) and its window.

Three optional keys steer rendering: ``source`` (``"tickets"`` by default,
or ``"projects"``, ``"wiki"``), ``needs`` (``"cost"`` or ``"rates"`` — who
may see the card at all) and ``money`` (the numbers are amounts).

``family`` is how the query answers: ``days`` for one series per day over
the range, ``rows`` for a list of ``(label, number)``, and ``groups`` for
labels that are not days — sprints — with several series, rendered like
``days``. ``group`` places a kind in the picker rail.
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
        "size": {"w": 6, "h": 4},
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
        "size": {"w": 6, "h": 4},
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
        "size": {"w": 6, "h": 4},
        "group": "people",
    },
    "velocity": {
        "title": "Velocity",
        "description": "Points committed against points completed, sprint by sprint.",
        "chart": "bar",
        "family": "groups",
        "charts": ["bar", "line", "table"],
        "x_label": "Sprint",
        "y_label": "Points",
        "how": (
            "The report's first project is shown on its own. Each closed "
            "sprint counts the points of the issues that were in it, and the "
            "points of those finished by the time it closed."
        ),
        "size": {"w": 6, "h": 4},
        "group": "projects",
        "source": "projects",
    },
    "burndown": {
        "title": "Burndown",
        "description": "Points still open in the current sprint, day by day.",
        "chart": "line",
        "family": "groups",
        "charts": ["line", "bar"],
        "x_label": "Day",
        "y_label": "Points left",
        "how": (
            "The report's first project is shown on its own, using its active "
            "sprint. Each day shows the points that were still not done at the "
            "end of that day."
        ),
        "size": {"w": 6, "h": 4},
        "group": "projects",
        "source": "projects",
    },
    "cost_by_project": {
        "title": "Cost by project",
        "description": "Money spent on finished work, per project.",
        "chart": "bar",
        "family": "rows",
        "charts": ["bar", "table"],
        "x_label": "Project",
        "y_label": "Spent",
        "how": (
            "Every finished issue outside the epics is priced from its points "
            "and the pay of whoever completed it, and added up per project. "
            "Issues we cannot price are left out."
        ),
        "size": {"w": 6, "h": 4},
        "group": "projects",
        "source": "projects",
        "needs": "cost",
        "money": True,
    },
    "cost_by_sprint": {
        "title": "Cost by sprint",
        "description": "Money spent on finished work, per closed sprint.",
        "chart": "bar",
        "family": "rows",
        "charts": ["bar", "line", "table"],
        "x_label": "Sprint",
        "y_label": "Spent",
        "how": (
            "Closed sprints are shown oldest first, the latest twelve at most. "
            "Each sprint adds up the price of the finished issues outside the "
            "epics that sat in it."
        ),
        "size": {"w": 6, "h": 4},
        "group": "projects",
        "source": "projects",
        "needs": "cost",
        "money": True,
    },
    "cost_per_point": {
        "title": "Cost per point",
        "description": "What a story point of finished work costs, per person.",
        "chart": "bar",
        "family": "rows",
        "charts": ["bar", "table"],
        "x_label": "Person",
        "y_label": "Cost per point",
        "how": (
            "For each person we can price, the cost of their finished work is "
            "divided by its story points. People with no points are left out."
        ),
        "size": {"w": 6, "h": 4},
        "group": "projects",
        "source": "projects",
        "needs": "rates",
        "money": True,
    },
    "wiki_activity": {
        "title": "Wiki activity",
        "description": "Pages created and edited per day, over the report's range.",
        "chart": "line",
        "family": "days",
        "charts": ["line", "bar", "table"],
        "x_label": "Day",
        "y_label": "Pages",
        "how": (
            "Pages count on the day they were created. An edit is a later "
            "saved version of a page, counted on the day it was saved."
        ),
        "size": {"w": 6, "h": 4},
        "group": "wiki",
        "source": "wiki",
    },
    "wiki_top_pages": {
        "title": "Most-read pages",
        "description": "The ten wiki pages with the most views.",
        "chart": "bar",
        "family": "rows",
        "charts": ["bar", "table"],
        "x_label": "Page",
        "y_label": "Views",
        "how": (
            "Every page carries its running view count. The ten highest are "
            "shown, most-read first; equal counts go alphabetical by title."
        ),
        "size": {"w": 6, "h": 4},
        "group": "wiki",
        "source": "wiki",
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
    "velocity": queries.velocity,
    "burndown": queries.burndown,
    "cost_by_project": queries.cost_by_project,
    "cost_by_sprint": queries.cost_by_sprint,
    "cost_per_point": queries.cost_per_point,
    "wiki_activity": queries.wiki_activity,
    "wiki_top_pages": queries.wiki_top_pages,
}

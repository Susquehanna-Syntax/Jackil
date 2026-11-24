# Architecture

Jackil is a self-hosted service desk and work tracker. One install serves one
organization, split into departments. It handles tickets, projects, a wiki, and
items, and you can link any of them to each other.

Jackil does not serve several organizations from one install. Monitored
machines belong to Vigil. Jackil reads them through the Vigil integration and
never runs anything on them.

## Technology

- **Django 5.2 (LTS)** with **Django REST Framework** for the API.
- **PostgreSQL** for production. **SQLite** for local testing (`USE_SQLITE=1`).
- **WhiteNoise** serves the static files.
- Pages are built with Django templates. A little JavaScript adds
  interactivity. There is no single-page app framework. The styles are in
  `static/css/style.css`.
- Scheduled work runs as management commands that cron calls, such as checking
  email and SLA deadlines. Jackil needs no Celery or Redis.

## Parts of the application

The data models are in `apps/*/models.py`. The main apps are:

| App | Holds |
|---|---|
| `accounts` | Users, roles, and departments |
| `tickets` | Tickets, their conversation, attachments, SLA data, and custom fields |
| `inbox` | Email inboxes, outgoing email, and incoming email |
| `sla` | SLA targets, business hours, and breach checks |
| `automation` | Macros and automation rules |
| `kb` | The knowledge base and the Help Center |
| `api` | The REST API, API keys, and webhooks |
| `reports` | Saved reports and CSV export |
| `projects` | Projects, issues, boards, backlogs, and sprints |
| `wiki` | Spaces, pages, page history, templates, and attachments |
| `links` | Dynamic Links between objects |
| `items` | Dynamic Items and their records |
| `dashboards` | Dashboards and their widgets |
| `portals` | Customer portals, one per department |
| `vigil` | The connection to Vigil |
| `licensing` | Edition checks for SQSY Business |
| `saml` | Single sign-on with SAML (SQSY Business) |

Jackil has three layers:

1. **Data.** The models store the records.
2. **Services.** Plain functions and management commands hold the business
   logic, such as SLA times, email parsing, and automation rules. Views and the
   API both call these functions, so the same rule applies in the web interface,
   the API, and cron jobs.
3. **Screens and API.** Django views and templates serve the web interface.
   Django REST Framework serves the API.

## Roles and permissions

Each user has one role.

- **Customer.** Sees only their own tickets. Can open tickets and post public
  replies. Cannot see internal notes or management controls.
- **Agent.** Sees all tickets. Can assign tickets, change status and priority,
  post internal notes, and use macros.
- **Admin.** Can do everything an agent can. Can also change configuration: SLA
  policies, automation rules, custom fields, request forms, inboxes, API keys,
  and users.

## Main records

- **Ticket.** The unit of work. A ticket has a title, description, status,
  priority, requester, assignee, watchers, department, tags, and timestamps. It
  also stores the due date, SLA times, the requester's email address, custom
  field values, and the source (web, email, or API).
- **Ticket message.** One entry in a ticket's conversation. Each entry has a
  kind: a public reply, an internal note, incoming email, outgoing email, or a
  system event. Each entry also has an author, a public or internal flag, and
  email headers. The ticket page shows all entries in date order. Customers see
  only public entries.
- **Attachment.** A file attached to a ticket or a message.
- **Department.** A group of agents and tickets.

## How the main flows work

- **Replies.** When an agent or customer posts a public reply, Jackil saves it on
  the ticket. If the requester can receive email, Jackil sends the reply from
  the ticket's inbox.
- **Incoming email.** The `poll_inbox` command connects to each inbox over IMAP
  and reads new messages. It adds each message to the matching ticket, using the
  plus-address token or the `[#id]` subject tag. If no ticket matches, it opens a
  new one. Messages are stored with their attachments.
- **SLAs.** When a ticket is created or changed, Jackil works out its response
  and resolution due times from the SLA policy and business hours. The
  `check_sla` command runs on a schedule. It marks breaches and sends
  escalations.
- **Automation.** When a ticket changes, Jackil checks the automation rules. A rule
  has conditions and actions. Actions can assign the ticket, set its priority,
  add a tag, send a macro, or escalate it.

## Building blocks

- **Dynamic Links.** One link table joins any two objects. The objects can be
  tickets, issues, pages, items, or Vigil hosts, tasks, playbooks, runs, and
  automations. Each type is listed in a registry that says how to search for it
  and how to show it. The link picker and the "Linked" panels both use the
  registry.
- **Projects.** A project holds issues, columns, sprints, and sub-tasks. Each
  issue has a key, such as `OPS-12`. The board and backlog run in the browser and
  read JSON data from the server.
- **Wiki.** A wiki has spaces and pages arranged in a tree. Each page keeps its
  history, so you can compare versions. Pages also have templates and
  attachments. Markdown is converted to HTML on the server and cleaned before it
  is shown.
- **Dynamic Items.** Admins define kinds of items. Each item has a record and
  custom fields. Device-type items are kept in Vigil once Vigil accepts device
  changes. Jackil keeps only links to the Vigil device and host.
- **Lists and tabs.** Lists filter as you type. Tabs use a color for each type.
  The filtering script is `static/js/jackil-filter.js`, and the tab bar is
  `templates/partials/tab_bar.html`.
- **Dashboards and reports.** Dashboards and saved reports use the same widgets.
  Widgets are defined in one registry. The same drawing script,
  `static/js/jackil-widgets.js`, draws them on both Jackil and Vigil pages.
- **Portals.** Each department can have a customer portal. Customers never see
  Vigil data or costs. Only admins see wages.
- **Vigil integration.** Jackil connects to Vigil from the server. You give Jackil
  the Vigil address and a key. The key is an integration key (`vjk_`), or a
  scoped API key (`vsk_`) that limits access to some sites. Jackil stores the key
  encrypted. It uses Vigil to search, show details, and fetch widget data.

  Jackil first asks Vigil which features it has, so Jackil never asks for a feature
  an older Vigil does not have. Jackil can write only device records, and only
  when the Vigil admin enables **Can change devices** on the key. Users do not
  need accounts in both apps.
- **Edition.** Jackil reads the SQSY Business license from the linked Vigil and
  checks its signature. A valid license turns on the Business features: SAML,
  portal branding, CSV export, the audit log, and CSAT ratings. Without a
  license, Jackil runs the Community edition. The check is `feature_enabled(slug)`.
- **SAML.** Single sign-on uses python3-saml. It is available only when
  `feature_enabled("saml")` is true.

## What Jackil does not do

- Serve more than one organization from one install.
- Monitor machines, run agents, or run actions on machines. Vigil does that.
- Offer live chat or websockets. Email and threaded comments handle messages.
- Handle billing or payments.

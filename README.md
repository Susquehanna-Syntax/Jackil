# Jackil

Free and open-source service desk and work tracker for one organization with
departments: tickets, projects, a wiki and an inventory of items, all linked
to each other. Built with Django, on the SQSY design language shared with
Vigil.

**Full documentation:** open [`docs/wiki.html`](docs/wiki.html) in a browser
for a single-page guide covering setup, day-to-day use, and the API.

## Tech Stack

- **Backend:** Django 5.2 (LTS) + Django REST Framework
- **Database:** PostgreSQL (production) / SQLite (zero-dependency local dev)
- **Front end:** server-rendered templates and plain JavaScript, no build step
- **Static:** WhiteNoise
- **Background work:** management commands (`poll_inbox`, `check_sla`) via cron,
  with no Celery or Redis dependency
- **Containerization:** Docker + Docker Compose (amd64 and arm64 images)

## Features

### Tickets and email
- One conversation per ticket: public replies, internal notes (agents only),
  inbound and outbound email, and system events
- File attachments on messages, with access-controlled downloads
- Two-way email: per-inbox SMTP/IMAP, `poll_inbox` threads inbound mail onto
  tickets (plus-address token or `[#id]` subject), replies email the requester
- SLA targets per priority on a business-hours schedule, breach detection and
  escalation (`check_sla`), due dates
- Custom fields and request forms; automation rules and canned-response macros
- Saved views, global search, in-app notifications

### Projects
- Projects with a board, a backlog, sprints and sub-tasks
- Issue keys (`OPS-12`), columns per project, story points and a velocity chart

### Wiki
- Spaces and nested pages written in Markdown, with a side-by-side preview,
  page history and diffs, templates and attachments
- "Linked from" on every page, and suggested articles on tickets

### Dynamic Links and Items
- Link anything to anything: a ticket to an issue, a page to an item, a host in
  Vigil to a ticket. Each link has a relation and shows up on both ends
- **Items:** an inventory of laptops, licences, contracts and anything else
  your organization tracks, with custom types, fields and warranty dates

### Dashboards and reports
- Dashboards built from widgets: counts, charts, gauges and tables over
  tickets, projects and, when linked, Vigil hosts
- Saved reports with sources, a date range and a grid of charts

### Customer portals
- A portal for each department with its own name, colours and request forms;
  customers see their own tickets and the help center, and never see Vigil data
  or costs

### Vigil integration
- With a Vigil integration key (`vjk_`), or a Vigil SQSY Business scoped API
  key (`vsk_`) to limit Jackil to some sites, Jackil reads hosts, tasks,
  playbooks, runs and automations from Vigil. Agents link them to tickets and
  put them on dashboards; Vigil shows what links to its objects. Jackil never
  runs anything in Vigil.

### SQSY Business
Unlocked by an SQSY Business licence on the Vigil instance Jackil is linked
to; Jackil verifies the licence itself.
- SAML single sign-on
- Portal branding, CSV export, audit log, CSAT ratings

### REST API
- Token-authenticated REST API (`/api/v1/`) with outbound webhooks, per-user
  and anonymous rate throttling, and a bounded page size (`?page_size=`)

## Quick Start (local dev, SQLite — no Postgres needed)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env (gitignored) — minimal local config
cat > .env <<'ENV'
DEBUG=1
USE_SQLITE=1
SECRET_KEY=dev-only-change-me
ENV

python manage.py migrate
python manage.py seed_demo --fresh   # demo departments, users, tickets, KB, forms
python manage.py runserver
```

Visit `http://localhost:8000`. Demo logins: `admin` / `admin12345` (admin),
`aria` / `password123` (agent), `jordan` / `password123` (customer).

### Run with Docker (PostgreSQL)

```bash
docker compose up --build
```

### Behind a reverse proxy / external hostname

When Jackil is reached through a proxy or a hostname other than `localhost`,
set both env vars so Django accepts logins and other POSTs:

```bash
ALLOWED_HOSTS=jackil-tail.kingdom.local,help.acme.com
CSRF_TRUSTED_ORIGINS=https://jackil-tail.kingdom.local,https://help.acme.com
```

`CSRF_TRUSTED_ORIGINS` must include the scheme. Without it, POSTs fail with
`Forbidden (Origin checking failed … does not match any trusted origins.)`.

## Background jobs (cron)

```bash
python manage.py poll_inbox    # fetch inbound email over IMAP
python manage.py check_sla     # flag SLA breaches and escalate
```

## Project layout

```
apps/
├── accounts/       User (roles), Department, profile
├── tickets/        Ticket, TicketMessage, Attachment, TicketRating, SavedView, domain signals (events.py)
├── inbox/          Inbox (SMTP/IMAP), outbound email, inbound ingest
├── sla/            SLA targets, business schedule, engine, check_sla
├── automation/     Macros + automation rules engine
├── kb/             Knowledge base / Help Center
├── projects/       Projects, issues, boards, backlogs, sprints
├── wiki/           Spaces, pages, revisions, templates, attachments
├── links/          Dynamic Links: the link registry and the link picker
├── items/          Items: inventory types, fields and records
├── dashboards/     Dashboards and their widgets
├── reports/        Saved reports and CSV export
├── portals/        Customer portals per department
├── vigil/          The Vigil connection: client, search, widgets, status embeds
├── licensing/      Edition: verifies the SQSY Business licence from Vigil
├── saml/           SAML single sign-on (SQSY Business)
├── civilsso/       Civil SSO
├── api/            REST API (DRF), API keys, webhooks
├── customfields/   Custom fields + request forms
├── notifications/  In-app notifications
└── console/        Admin settings console + branding
```

Engineering docs live under `docs/` — `architecture.md`, the milestone/phase
history in `dev/`, and the single-page user guide `wiki.html`.

## License

AGPLv3 — see [LICENSE](LICENSE). SQSY Business features are unlocked by an
SQSY Business licence on the Vigil instance Jackil is linked to.

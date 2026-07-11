# Jackil

Free and open-source IT ticket-management (helpdesk) software for a single
organization with departments. Built with Django, with a warm-dark, pastel
design system.

📖 **Full documentation:** open [`docs/wiki.html`](docs/wiki.html) in a browser
for a single-page guide covering setup, day-to-day use, and the API.

## Tech Stack

- **Backend:** Django 5.2 (LTS) + Django REST Framework
- **Database:** PostgreSQL (production) / SQLite (zero-dependency local dev)
- **Static:** WhiteNoise
- **Background work:** management commands (`poll_inbox`, `check_sla`) via cron —
  no Celery/Redis dependency
- **Containerization:** Docker + Docker Compose

## Features

### Conversations & Email
- Unified conversation thread per ticket: public replies, internal notes
  (agents only), inbound/outbound email, and system audit events
- File attachments on messages, access-controlled downloads
- Two-way email: per-inbox SMTP/IMAP config, `poll_inbox` threads inbound mail
  onto tickets (plus-address token / `[#id]` subject), replies email the requester

### SLA, Due Dates & Escalation
- SLA response/resolution targets per priority, business-hours schedule
- Auto-computed due times, first-response clock, breach detection (`check_sla`),
  auto-escalation, due dates, dashboard "Needs Attention" widget

### Automation, Knowledge Base, Reporting & API
- Automation rules (trigger → conditions → actions) and canned-response macros
- Public Help Center with categories/articles + admin authoring
- Reporting dashboard: volume, status/priority mix, SLA compliance, CSAT, agent load
- Token-authenticated REST API (`/api/v1/`) + outbound webhooks, with per-user/
  anon rate throttling and a bounded, client-overridable page size (`?page_size=`)

### Custom Fields & Request Forms
- Admin-defined custom fields (text, dropdown, checkbox, number, date)
- Request forms that drive dynamic customer intake; values shown on the ticket

### Search, Saved Views, Notifications & More
- Global search across tickets and the knowledge base (permission-scoped)
- **Saved views** — persist named ticket-list filter sets (status/priority/
  assignment/search), recall in one click, share with the team
- In-app notifications with unread badge; user profiles and preferences
- Roles (customer / agent / admin) with role-based access throughout

### Pro / Enterprise
- CSV data export, activity/audit log, CSAT (satisfaction) ratings
- White-label branding (product name, tagline, accent color)

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
├── api/            REST API (DRF), API keys, webhooks
├── reports/        Reporting & analytics
├── customfields/   Custom fields + request forms
├── notifications/  In-app notifications
└── console/        Admin settings console + branding
```

Engineering docs live under `docs/` — `architecture.md`, the milestone/phase
history in `dev/`, and the single-page user guide `wiki.html`.

## License

Free and open source.

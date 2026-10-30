# Jackil — Architecture

Jackil is a self-hosted **service desk and work tracker** for a **single
organization** divided into departments: tickets, projects, a wiki and items,
joined by Dynamic Links. It is not multi-tenant: one install serves one org.
Monitored machines belong to the sibling product, Vigil; Jackil reads them
through the Vigil integration and never runs anything there.

## Stack

- **Django 5.2** (LTS), **Django REST Framework** for the API.
- **Postgres** in production; **SQLite** in local dev (`USE_SQLITE=1`).
- **whitenoise** for static serving.
- Server-rendered templates (Django templates) with progressive-enhancement
  JavaScript. No SPA framework. Design system in `static/css/style.css`.
- Background/periodic work runs as **management commands** invoked by cron
  (email polling, SLA escalation checks) — no Celery/Redis dependency.

## Layers

1. **Data** — Django models in `apps/*/models.py`. Core apps: `accounts`
   (User, Department), `tickets` (Ticket, conversation, attachments, SLA,
   custom fields), plus feature apps added per milestone (`inbox`, `automation`,
   `kb`, `api`, `reports`, and in 2026.3 `projects`, `wiki`, `links`, `items`,
   `dashboards`, `portals`, `vigil`, `licensing`, `saml`).
2. **Domain/services** — plain functions and management commands that implement
   business logic (SLA computation, email rendering/parsing, automation-rule
   evaluation). Kept out of views so they are unit-testable and reusable from
   the API, cron, and the UI.
3. **Presentation** — Django views + templates for the human UI; DRF
   viewsets/serializers for the machine API. Both call the same domain layer.

## Roles & permissions

`accounts.User.role` ∈ {`customer`, `agent`, `admin`}.

- **customer** — end user; sees only their own tickets, can create tickets and
  post public replies, cannot see internal notes or management controls.
- **agent** — support staff; sees all tickets, assigns, changes status/priority,
  posts internal notes, uses macros.
- **admin** — everything agents can do, plus configuration (SLA policies,
  automation rules, custom fields, request forms, inboxes, API keys, users).

Permission helpers live in `apps/tickets/permissions.py` (extracted from the
`_can_*` functions currently inline in `views.py`).

## Core data model

- **Ticket** — the unit of work. Fields today: title, description, status,
  priority, created_by, assigned_to, assigned_users (M2M watchers/collaborators),
  department, tags, timestamps, closed_at. Grows: `due_at`, SLA timestamps,
  `requester_email`, `custom field values`, `source` (web/email/api).
- **TicketMessage** — unified conversation entry replacing the old
  `TicketComment`. `kind` ∈ {`reply` (public), `note` (internal),
  `incoming_email`, `outgoing_email`, `system` (audit event)}. Carries body,
  author (nullable for email/system), `is_public`, email metadata
  (message-id, in-reply-to, from address), created_at. The ticket detail page
  renders these as a single chronological thread; customers see only public
  entries.
- **Attachment** — a file attached to a ticket or a message (`apps.tickets`).
- **Department** — grouping of agents and tickets.

## Major data flows

- **Web reply** — agent/customer posts a message on the ticket detail page →
  `TicketMessage` created → if `kind=reply` and the requester is reachable by
  email, an outbound email is queued/sent via the ticket's inbox.
- **Inbound email** — `manage.py poll_inbox` connects to each configured Inbox
  over IMAP, parses new messages, threads them onto the matching ticket (by
  plus-addressed token or subject `[#id]`), creating a new ticket when none
  matches. Stored as `incoming_email` messages with attachments.
- **SLA** — on ticket create/update, `apps/tickets/sla.py` computes response and
  resolution due times from the applicable SLA policy and business hours.
  `manage.py check_sla` runs periodically to flag breaches and fire escalations.
- **Automation** — on ticket events, `apps/automation` evaluates rules
  (conditions → actions) and applies matching actions (assign, set priority,
  add tag, send macro, escalate).

## 2026.3 building blocks

- **Dynamic Links** (`apps/links`) — one `DynamicLink` table joins any two objects
  (ticket, issue, page, item, or a Vigil host, task, playbook, run or
  automation) with a relation. A registry names each type, how to search it
  and how to show it; the link picker and every "Linked" panel read that
  registry, so a new type is one registry entry.
- **Projects** (`apps/projects`) — Project, Issue (with a per-project key such
  as `OPS-12`), columns, sprints and sub-tasks; board and backlog are plain
  JavaScript over JSON endpoints.
- **Wiki** (`apps/wiki`) — Space, Page (tree), PageVersion (history and diffs),
  PageTemplate, PageAttachment. Markdown rendered server-side and sanitised.
- **Dynamic Items** (`apps/items`) — admin-defined kinds (`ItemKind`, with
  `is_device_like` and a Vigil device type) and `Item` records. Device-like
  items live in Vigil once Vigil allows device writes (`apps/vigil/devices.py`,
  `apps/vigil/move.py`): Jackil stores only links to `vigil:device` and
  `vigil:host`.
- **UI kit** (`apps/ui`, `static/js/jackil-filter.js`,
  `templates/partials/tab_bar.html`) — lists filter as you type through
  `?partial=1` fragments; coloured tabs as in Vigil.
- **Dashboards and reports** (`apps/dashboards`, `apps/reports`) — a widget
  registry (kind, shape, settings) shared by dashboards and saved reports, and
  one drawing script, `static/js/jackil-widgets.js`, which Vigil also uses for
  Jackil widgets.
- **Portals** (`apps/portals`) — a customer-facing portal per department.
  Customers never see Vigil data or costs; only admins see wages.
- **Vigil integration** (`apps/vigil`) — server to server. Jackil stores the
  Vigil address and a key (an integration key `vjk_`, or a Vigil SQSY
  Business scoped key `vsk_` limited to some sites), encrypted at rest, and
  calls Vigil's integration endpoints for search, detail and widget data.
  `ping` lists capabilities (`devices`, `host_facts`, `device_write`), so an
  older Vigil is never asked for what it lacks. The only writes are device
  create, update and delete, and only when the key's `can_write_devices` flag
  is set in Vigil. No per-user mapping between the two apps.
- **Edition** (`apps/licensing`) — Jackil reads the signed SQSY licence blob
  from the linked Vigil and verifies it itself (Ed25519, instance binding, the
  `jackil` claim). A valid licence turns on the Business features (SAML,
  portal branding, CSV export, audit log, CSAT); without one Jackil is the
  full Community edition. `feature_enabled(slug)` is the only gate.
- **SAML** (`apps/saml`) — python3-saml, self-contained behind
  `feature_enabled("saml")` so it can move to a private package later.

## Non-goals

- Multi-tenancy / multiple organizations in one install.
- Monitoring, agents or remote actions on machines (owned by Vigil).
- Real-time chat / websockets (email + threaded comments cover messaging).
- Billing / payments.

## Milestone roadmap

- **M1 — Conversations & Email.** Unified `TicketMessage` thread, attachments,
  per-inbox SMTP/IMAP configuration, inbound email→ticket threading, outbound
  replies, internal notes, system/audit events. Front-loaded priority #1.
- **M2 — SLA, Due Dates & Escalation.** SLA policies, business hours, response &
  resolution timers, due dates, breach detection, escalation, dashboard SLA
  widgets. Front-loaded priority #2.
- **M3 — Automation, Knowledge Base, Reporting & API.** Automation rules &
  macros, knowledge base + public help center, analytics/reporting dashboards,
  REST API with API keys and webhooks. Front-loaded priority #3.
- **M4 — Custom Fields & Request Forms.** Admin-defined custom fields, per-
  category request forms, dynamic customer intake.
- **M5 — Search, History, Notifications & Dashboard Customization.** Global
  search, activity/audit history, saved views, notifications, dashboard
  customization, profile/settings, polish.
- **2026.3** — the SQSY design language and shell, dashboards, Dynamic Links
  and Items, the wiki, projects, saved reports, the Vigil integration,
  customer portals, the SQSY Business edition with SAML, and a UX pass.

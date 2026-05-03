# Jackil

Free and open source IT ticket management software for departments. Built with Django and deployed via Docker.

## Tech Stack

- **Backend:** Django 5.0
- **Database:** PostgreSQL 16
- **Containerization:** Docker + Docker Compose


## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- Python 3.12+ (for local development)

### Run with Docker

```bash
docker compose up --build
```

The app will be available at `http://localhost:8000`.

### Run Locally

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL=postgres://jackil:jackil123@localhost:5432/jackil
export SECRET_KEY=your-secret-key
export DEBUG=1

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run dev server
python manage.py runserver
```

Visit `http://localhost:8000` to see the landing page.

## Project Structure

```
Jackil/
├── Dockerfile                 # Production container (Gunicorn)
├── docker-compose.yml         # Web + PostgreSQL services
├── requirements.txt           # Python dependencies
├── manage.py                  # Django management
├── entrypoint.sh              # Migration entrypoint
│
├── config/                    # Project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── apps/
│   ├── accounts/              # Custom user model, auth
│   │   ├── models.py          # User (AbstractUser), Department
│   │   ├── views.py           # Login, register, logout
│   │   └── admin.py
│   │
│   └── tickets/               # Ticket management
│       ├── models.py          # Ticket, TicketComment
│       ├── views.py           # CRUD views
│       ├── admin.py
│       └── urls.py
│
├── templates/                 # HTML templates
│   ├── base.html              # Frosted glass sidebar layout
│   ├── accounts/              # Login, Register
│   └── tickets/               # Dashboard, list, detail, forms
│
    ├── static/
│   └── css/style.css          # CSS styles
```

## Features

- **Ticket Management:** Create, edit, assign, and close IT tickets
- **User Roles:** Admin, Agent, User with role-based access
- **Departments:** Group tickets by department
- **Priorities:** Critical, High, Medium, Low
- **Statuses:** Open, In Progress, Pending, Resolved, Closed
- **Comments:** Add comments to tickets for team communication
- **Tagging:** Tag tickets for easy filtering
- **Dashboard:** Overview with stats and recent tickets
- **Search & Filter:** Filter tickets by status, priority, and assignment


## Database

By default, PostgreSQL runs in Docker Compose. Connection details:

| Setting | Value |
|---------|-------|
| Host | db |
| Port | 5432 |
| Database | jackil |
| User | jackil |
| Password | jackil123 |

For local development with a local PostgreSQL instance, update `DATABASES` in `config/settings.py` or set the environment variables accordingly.

## Admin

Access Django admin at `http://localhost:8000/admin/`.

Create an admin user:

```bash
docker exec -it jackil_web python manage.py createsuperuser
```

Or locally:

```bash
python manage.py createsuperuser
```

## License

Free and open source.
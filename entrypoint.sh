#!/bin/bash
set -e

# Prepare the app on boot: apply migrations and gather static files
# (WhiteNoise serves them from STATIC_ROOT under gunicorn).
python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"

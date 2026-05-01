#!/bin/bash
set -e

if [ "$DATABASE_URL" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
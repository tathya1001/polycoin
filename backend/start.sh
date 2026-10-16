#!/bin/sh
# Production entrypoint (Render). Contains no migrations: those run once per release in the
# CI/CD pipeline, and static files are collected at image build time.
# Local development overrides this with runserver in docker-compose.yml.
set -e

# exec replaces the shell, so gunicorn gets Render's shutdown signal directly.
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 60 \
    --access-logfile -

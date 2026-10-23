#!/bin/sh
# Production entrypoint (Render). Contains no migrations: those run once per release in the
# CI/CD pipeline, and static files are collected at image build time.
# Local development overrides this with runserver in docker-compose.yml.
set -e

# exec replaces the shell, so gunicorn gets Render's shutdown signal directly.
# --preload: the master imports the app once (Django, every view, the RAG libraries) and forks the
# workers, which share that memory. Measured at Render's limits (0.1 CPU, 512 MB): first response
# after 19 s instead of 51 s (each worker importing on its own share of 0.1 CPU), and 113 MB
# instead of 194 MB. config/wsgi.py closes database connections before the fork.
exec gunicorn config.wsgi:application \
    --preload \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 60 \
    --access-logfile -

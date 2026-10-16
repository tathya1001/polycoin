FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Production images skip test and lint tools; docker-compose.yml sets INSTALL_DEV=true locally.
ARG INSTALL_DEV=false
COPY requirements.txt requirements-dev.txt /app/
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

COPY . /app

# Collect static files once, at build time. settings.py reads required secrets at import, so we
# pass throwaway values for this one command only; they aren't stored in the image's environment.
RUN DJANGO_PRODUCTION=TRUE \
    DJANGO_SECRET_KEY=build-only \
    JWT_SIGNING_KEY=build-only \
    DJANGO_ALLOWED_HOSTS=localhost \
    CSRF_TRUSTED_ORIGINS=http://localhost \
    FIELD_ENCRYPTION_KEYS=v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= \
    FIELD_ENCRYPTION_ACTIVE_KEY=v1 \
    python manage.py collectstatic --noinput

# Unprivileged user: a compromised process can't rewrite the app's code.
RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
CMD ["sh", "start.sh"]

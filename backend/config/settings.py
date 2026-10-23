"""Django settings. Secrets and per-environment values come from environment variables (see .env.example)."""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

AUTH_USER_MODEL = "accounts.User"


# Required, with no default: the app refuses to start without it.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# Off unless the variable is exactly TRUE.
DEBUG = os.environ.get("DJANGO_DEBUG") == "TRUE"

# Production (Render). Off locally, where everything is plain http on localhost.
PRODUCTION = os.environ.get("DJANGO_PRODUCTION") == "TRUE"

ALLOWED_HOSTS = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")
# Render sets this to the service's own *.onrender.com name.
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "core",
    "accounts",
    "vault",
    "categories",
    "transactions",
    "insights",
    "ai",
]


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'core.middleware.OriginSecretMiddleware',
    'core.middleware.NoStoreApiMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if PRODUCTION:
    # Serves the admin's collected static files (Render has no nginx). Right after
    # SecurityMiddleware so static requests are answered before sessions and auth run.
    # Only in production: locally the image's staticfiles/ is hidden by the bind mount.
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Neon suspends idle computes and drops their connections; the health check replaces a dead
# persistent connection instead of failing the request.
DATABASES = {"default": dj_database_url.config(conn_max_age=600, conn_health_checks=True)}


# Password hashing
# New passwords use the first hasher; the others only verify older hashes.

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic target, served by WhiteNoise


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.CookieJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "auth": "5/min",
        "import": "10/hour",
        "ai": "20/hour",
        "ai_light": "120/hour",
        "insights": "600/hour",
        "destructive": "5/hour",  # erasing all data; also caps password guessing through it
        # Ask your transactions. Indexing is two calls per 100 rows (pending, then
        # vectors). Asking decrypts the whole index, so scripted bulk decryption is capped.
        "rag_index": "300/hour",
        "rag_ask": "60/hour",
    },
}


# JWT in httpOnly cookies

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=10),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "SIGNING_KEY": os.environ["JWT_SIGNING_KEY"],  # separate from SECRET_KEY
}

AUTH_COOKIE_ACCESS = "access"
AUTH_COOKIE_REFRESH = "refresh"
AUTH_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "TRUE") == "TRUE"
AUTH_COOKIE_SAMESITE = "Lax"
AUTH_COOKIE_REFRESH_PATH = "/api/accounts/"


CSRF_TRUSTED_ORIGINS = os.environ["CSRF_TRUSTED_ORIGINS"].split(",")
FIELD_ENCRYPTION_KEYS = os.environ["FIELD_ENCRYPTION_KEYS"]
FIELD_ENCRYPTION_ACTIVE_KEY = os.environ["FIELD_ENCRYPTION_ACTIVE_KEY"]


# Production hardening (DJANGO_PRODUCTION=TRUE)

if PRODUCTION:
    # Render terminates TLS and forwards plain http, recording the original scheme in this
    # header. Trusting it is safe because the container is only reachable through Render's proxy.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    # Render's health checker may call over plain http, and a redirect would read as unhealthy.
    SECURE_REDIRECT_EXEMPT = [r"^api/ping/$"]
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "3600"))
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

    # Throttle counters must be shared by every gunicorn worker and survive restarts; the
    # default in-memory cache is per process, which would multiply the login limit.
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "django_cache",
        }
    }

    # No debug page in production, so errors must reach stdout for Render's log viewer.
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler"}},
        "root": {"handlers": ["console"], "level": "INFO"},
    }

# onrender.com and vercel.app are shared parent domains we don't own, so HSTS can't include
# subdomains or be preloaded.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]


# AI categorisation. The server never calls Ollama: it prepares a run, and the user's browser
# embeds it with the user's own Ollama and scores it (frontend/lib/ollama.ts, lib/scoring.ts).
# The scoring thresholds below are sent to the browser with each run, so they live in one place.

AI_MAX_RUN = int(os.environ.get("AI_MAX_RUN", "200"))  # transactions scored per run
AI_MAX_EXAMPLES_PER_CATEGORY = int(os.environ.get("AI_MAX_EXAMPLES_PER_CATEGORY", "20"))
# Tuned on 22 realistic bank-statement narrations with nomic-embed-text: nonsense scores about
# 0.35-0.45 and real matches 0.47+, while AI_MIN_MARGIN is what rejects ambiguous rows.
AI_MIN_SCORE = float(os.environ.get("AI_MIN_SCORE", "0.45"))  # best cosine score to propose
AI_MIN_MARGIN = float(os.environ.get("AI_MIN_MARGIN", "0.05"))  # best must beat runner-up by this
AI_BLEND_FULL_AT = int(os.environ.get("AI_BLEND_FULL_AT", "10"))  # examples at which the blend maxes out
AI_BLEND_MAX_WEIGHT = float(os.environ.get("AI_BLEND_MAX_WEIGHT", "0.7"))  # max pull toward the user's examples

# Insights decrypts rows in Python, so one request must never load an unbounded number of them.
INSIGHTS_MAX_ROWS = int(os.environ.get("INSIGHTS_MAX_ROWS", "50000"))

# "Ask your transactions" (RAG). The browser embeds with the user's own Ollama; the server stores
# the encrypted vectors and searches them.
RAG_MAX_DIMS = int(os.environ.get("RAG_MAX_DIMS", "4096"))  # largest vector accepted (cap 4096)
# Kill switch: FALSE turns the feature off with an environment change and no deploy.
RAG_ENABLED = os.environ.get("RAG_ENABLED", "TRUE") == "TRUE"
RAG_INDEX_BATCH = int(os.environ.get("RAG_INDEX_BATCH", "100"))  # rows per embed round trip
# One ask searches at most this many documents, newest first: about a second at Render's 0.1 CPU.
# A period reaches older rows, and the page says how many were searched.
RAG_MAX_DOCS = int(os.environ.get("RAG_MAX_DOCS", "8000"))
RAG_MAX_MATCHES = int(os.environ.get("RAG_MAX_MATCHES", "50"))  # kept per ranking and after fusion
RAG_RRF_K = int(os.environ.get("RAG_RRF_K", "60"))  # reciprocal rank fusion constant
# An untuned model's vector matches: rows within this much of the best cosine score.
RAG_RELATIVE_MARGIN = float(os.environ.get("RAG_RELATIVE_MARGIN", "0.05"))
# The prompt lists the closest RAG_TOP_K matches (the summary still covers all of them), about
# 40 tokens each, so RAG_NUM_CTX tokens hold them, the rules and the answer with room to spare.
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "20"))
RAG_NUM_CTX = int(os.environ.get("RAG_NUM_CTX", "4096"))

# langchain-core installs the LangSmith client, and LangSmith tracing would send every prompt,
# which holds decrypted transactions, to a third party. It is forced off whatever the environment
# says, and the keys it would use are removed; ai/test_rag_api.py checks this.
for _name in (
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING",
    "LANGCHAIN_TRACING_V2",
):
    os.environ[_name] = "false"
for _name in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
    os.environ.pop(_name, None)

# Shared with the Vercel proxy, which sends it as X-Origin-Secret on every /api/ request;
# Django refuses /api/ requests without it. Empty (the default) turns the check off.
ORIGIN_SECRET = os.environ.get("ORIGIN_SECRET", "")

# The commit this process runs. Render sets it; the deploy pipeline waits for it to change.
GIT_COMMIT = os.environ.get("RENDER_GIT_COMMIT", "dev")

# Error tracking (Sentry). Off unless a DSN is set; see core/observability.py for what it
# keeps out of error reports.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    from core.observability import init_sentry

    init_sentry(SENTRY_DSN, release=GIT_COMMIT)

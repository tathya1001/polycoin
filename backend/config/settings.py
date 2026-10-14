"""Django settings. Secrets and per-environment values come from environment variables (see .env.example)."""

import os
import dj_database_url
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

AUTH_USER_MODEL = "accounts.User"


# Required, with no default: the app refuses to start without it.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# Off unless the variable is exactly TRUE.
DEBUG = os.environ.get("DJANGO_DEBUG") == "TRUE"

ALLOWED_HOSTS = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")


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
]


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware'    
]

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


DATABASES = {"default": dj_database_url.config(conn_max_age=600)}


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


# Local AI categorisation (Ollama embeddings)
# Optional, unlike the settings above: a missing Ollama must not stop the app booting.
# The URL comes from the environment only, never from a request.

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "60"))  # seconds, per HTTP call

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

"""Root URL configuration."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

# Every API view requires authentication by default (REST_FRAMEWORK
# DEFAULT_PERMISSION_CLASSES). These are the ONLY explicitly open (AllowAny) ones:
#   GET  /api/health/             readiness probe (checks the database)
#   GET  /api/ping/               liveness for keep-alive and Render; no DB access
#   GET  /api/accounts/csrf/      hands the browser its CSRF cookie
#   POST /api/accounts/register/  throttled
#   POST /api/accounts/login/     throttled
#   POST /api/accounts/refresh/   needs the refresh cookie + CSRF, throttled
#   POST /api/accounts/logout/    needs CSRF; revokes the refresh cookie if any
#   POST /api/accounts/recover/   forgot password: needs the recovery key, throttled
# core/tests.py fails if an endpoint is added to or removed from this list unnoticed.

urlpatterns = [
    path('api/', include('core.urls')),
    path('api/accounts/', include('accounts.urls')),
    path('api/', include('categories.urls')),
    path('api/', include('datasources.urls')),
    path('api/', include('transactions.urls')),
    path('api/', include('ai.urls')),
    path('api/', include('insights.urls')),
    path('api/', include('backups.urls')),
]

# The Django admin is for local development only. In production it would be a login form on the
# open internet with no throttle and no origin check, and an admin can reset any user's password,
# then sign in as them. config/test_urls.py checks it stays out.
if not settings.PRODUCTION:
    urlpatterns.append(path('admin/', admin.site.urls))

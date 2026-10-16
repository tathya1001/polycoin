"""Root URL configuration."""
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
# core/tests.py fails if an endpoint is added to or removed from this list unnoticed.

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('core.urls')),
    path('api/accounts/', include('accounts.urls')),
    path('api/', include('categories.urls')),
    path('api/', include('transactions.urls')),
    path('api/', include('ai.urls')),
    path('api/', include('insights.urls')),
]

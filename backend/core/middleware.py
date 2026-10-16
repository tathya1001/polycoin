import hmac

from django.conf import settings
from django.http import JsonResponse
from django.utils.cache import add_never_cache_headers

# Probes that must work without the Vercel proxy: Render's health check, the keep-alive cron
# and the deploy pipeline call these straight on the Render URL.
ORIGIN_EXEMPT = {"/api/ping/", "/api/health/"}


class OriginSecretMiddleware:
    """Refuse /api/ requests that did not come through our own Vercel proxy.

    The proxy adds `X-Origin-Secret`. Without this check anyone can call the Render URL
    directly and, among other things, forge X-Forwarded-For to dodge the login throttle.
    Off unless ORIGIN_SECRET is set, so local development and the rollout order don't matter:
    set it on Vercel first, then on Render.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        expected = settings.ORIGIN_SECRET
        if expected and request.path.startswith("/api/") and request.path not in ORIGIN_EXEMPT:
            sent = request.META.get("HTTP_X_ORIGIN_SECRET", "")
            # compare_digest keeps the comparison time independent of how much matched.
            if not hmac.compare_digest(sent.encode(), expected.encode()):
                return JsonResponse({"detail": "Forbidden."}, status=403)
        return self.get_response(request)


class NoStoreApiMiddleware:
    """Mark every API response uncacheable.

    Vercel's CDN may cache proxied responses that carry cache headers, and these responses are
    one user's private financial data. Stating `no-store` removes any chance of it being shared.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            add_never_cache_headers(response)  # max-age=0, no-cache, no-store, must-revalidate, private
        return response

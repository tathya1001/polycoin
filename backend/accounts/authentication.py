from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import exceptions
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from vault.services import unlock_session


def enforce_csrf(request):
    """Run Django's CSRF check against a DRF request.

    DRF only does this automatically for SessionAuthentication. Because we
    authenticate with a cookie, the browser attaches it to cross-site requests
    too, so we must check the CSRF token ourselves.
    """
    check = CsrfViewMiddleware(lambda req: None)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise exceptions.PermissionDenied(f"CSRF Failed: {reason}")


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate with the JWT access token stored in an httpOnly cookie, and open the user's
    data key from this browser's vault session (the "vault" cookie) for this request.

    A valid token without a vault session that opens is treated as anonymous (Phase 12.1, D6):
    signed in means the data is unlocked. The browser then refreshes, which needs the vault
    session too, and lands on the login page.
    """

    def authenticate(self, request):
        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)
        if raw_token is None:
            return None  # anonymous; IsAuthenticated will reject if required

        try:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
        except AuthenticationFailed:  # includes InvalidToken and unknown/inactive user
            # Expired/garbage cookie: treat as anonymous instead of failing the request.
            # Otherwise a stale cookie would 401 even public endpoints (register, health).
            # Protected views still reject anonymous users via IsAuthenticated (401).
            return None
        enforce_csrf(request)  # before opening anything: a forged request gets nothing unlocked
        if not unlock_session(user, request.COOKIES.get(settings.AUTH_COOKIE_VAULT)):
            return None
        return user, validated_token

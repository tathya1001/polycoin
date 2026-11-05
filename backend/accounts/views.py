import logging

from django.conf import settings
from django.db import transaction
from django.db.models import ProtectedError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import generics, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from vault.services import (
    WrongSecret,
    close_all_sessions,
    close_other_sessions,
    close_session,
    open_session,
    renew_session,
    replace_recovery_key,
    set_password_lock,
    unlock_with_password,
    unlock_with_recovery_key,
    unlocked_key,
)

from .authentication import enforce_csrf
from .limits import account_is_locked, record_failure, too_many_failures
from .models import User, UserPreferences
from .serializers import (
    BirthDateSerializer,
    ChangePasswordSerializer,
    ConfirmPasswordSerializer,
    PreferencesSerializer,
    RecoverSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .services import delete_account, delete_user_data, set_birth_date

logger = logging.getLogger(__name__)


def set_auth_cookies(response, access, refresh=None):
    """Put the JWTs into httpOnly cookies. JS can never read these."""
    common = {
        "httponly": True,
        "secure": settings.AUTH_COOKIE_SECURE,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
    }
    response.set_cookie(
        settings.AUTH_COOKIE_ACCESS,
        access,
        # The cookie outlives the token (the JWT's own exp is what enforces the 10 min).
        # That lets the frontend proxy see "this browser has a session" and lets
        # apiFetch refresh an expired token instead of bouncing the user to /login.
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        path="/",
        **common,
    )
    if refresh is not None:
        response.set_cookie(
            settings.AUTH_COOKIE_REFRESH,
            refresh,
            max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
            path=settings.AUTH_COOKIE_REFRESH_PATH,
            **common,
        )


def set_vault_cookie(response, value):
    """The browser's half of its vault session (Phase 12.1, D4): the only copy of the secret that
    opens its copy of the user's data key. httpOnly, and sent to the API only."""
    response.set_cookie(
        settings.AUTH_COOKIE_VAULT,
        value,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        path=settings.AUTH_COOKIE_VAULT_PATH,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


def clear_auth_cookies(response):
    # delete_cookie only matches if the path matches the one used to set it
    response.delete_cookie(settings.AUTH_COOKIE_ACCESS, path="/")
    response.delete_cookie(
        settings.AUTH_COOKIE_REFRESH, path=settings.AUTH_COOKIE_REFRESH_PATH
    )
    response.delete_cookie(settings.AUTH_COOKIE_VAULT, path=settings.AUTH_COOKIE_VAULT_PATH)


def revoke_refresh_tokens(user):
    """Blacklist every refresh token the user holds, so no browser can renew its login."""
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def create(self, request, *args, **kwargs):
        enforce_csrf(request)  # Phase 12.2, D1: no sign-ups from another site's forms
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            # Shown once by the app, and never again: nothing that could show it is stored.
            {"id": str(user.id), "email": user.email, "recovery_key": serializer.recovery_key},
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    """Check the password, open the user's data key with it, and lock a copy to this browser
    (Phase 12.1, D4).

    Phase 12.2: the CSRF token and Origin are checked (D1), so another site's form can't sign a
    visitor into an attacker's account; and failed logins are limited per account (D4)."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request, *args, **kwargs):
        enforce_csrf(request)
        email = request.data.get("email")
        if account_is_locked(email):
            return too_many_failures()
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0]) from e
        except AuthenticationFailed:
            record_failure(email)
            raise
        user = serializer.user

        try:
            dek = unlock_with_password(user, request.data["password"])
        except WrongSecret:
            # D11: the password was changed by a tool that doesn't know about the lock.
            return Response(
                {
                    "code": "key_locked",
                    "detail": "Your data is still locked with an earlier password. "
                    "Use your recovery key to set a new one.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        response = Response({"detail": "Logged in."})  # the tokens never reach the JS-visible body
        set_auth_cookies(
            response, serializer.validated_data["access"], serializer.validated_data["refresh"]
        )
        close_session(request.COOKIES.get(settings.AUTH_COOKIE_VAULT))  # a re-login replaces it
        set_vault_cookie(response, open_session(user, dek))
        return response


class RefreshView(APIView):
    # Skip cookie-JWT auth: the access token is usually expired when we get here.
    authentication_classes = []
    permission_classes = [AllowAny]
    # Not the strict login limit: a refresh proves itself with a signed token, so there is
    # nothing to guess, and several open tabs refresh at about the same time. Sharing "auth"
    # (5/min) turned that into 429s, which the browser treated as a lost session.
    throttle_scope = "refresh"

    def post(self, request):
        enforce_csrf(request)  # authentication_classes=[] disabled the automatic check
        raw_refresh = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if raw_refresh is None:
            return Response(
                {"detail": "No refresh token."}, status=status.HTTP_401_UNAUTHORIZED
            )

        serializer = TokenRefreshSerializer(data={"refresh": raw_refresh})
        try:
            serializer.is_valid(raise_exception=True)
        except (TokenError, InvalidToken) as e:
            # Return 401 ourselves: with authentication_classes=[], DRF would
            # downgrade a raised auth error to 403 (no WWW-Authenticate header).
            return Response({"detail": str(e)}, status=status.HTTP_401_UNAUTHORIZED)
        except User.DoesNotExist:
            # The account was deleted (simplejwt looks the user up without catching this). An
            # open tab of it lands here and must be signed out, not shown a 500.
            response = Response({"detail": "No account."}, status=status.HTTP_401_UNAUTHORIZED)
            clear_auth_cookies(response)
            return response

        # The login is only renewed with this browser's vault session (Phase 12.1, D6, D7):
        # without it nothing could be read, so the browser must sign in again.
        vault = request.COOKIES.get(settings.AUTH_COOKIE_VAULT)
        user_id = AccessToken(serializer.validated_data["access"])[jwt_settings.USER_ID_CLAIM]
        if not renew_session(user_id, vault):
            response = Response(
                {"detail": "Your session is locked. Sign in again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            clear_auth_cookies(response)
            return response

        response = Response({"detail": "Refreshed."})
        # ROTATE_REFRESH_TOKENS=True, so a new refresh token is issued each time
        set_auth_cookies(
            response,
            serializer.validated_data["access"],
            serializer.validated_data.get("refresh"),
        )
        set_vault_cookie(response, vault)  # renewed for as long as the login
        return response


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    age_check_exempt = True  # it is how the app learns it must ask for the date of birth

    def get_object(self):
        return self.request.user


class PreferencesView(generics.RetrieveUpdateAPIView):
    """GET / PATCH /api/accounts/preferences/: the signed-in user's own settings (font...)."""

    serializer_class = PreferencesSerializer
    http_method_names = ["get", "patch", "head", "options"]  # no PUT: PATCH is enough
    age_check_exempt = True  # the look only: the date-of-birth screen is drawn with it

    def get_object(self):
        preferences, _ = UserPreferences.objects.get_or_create(user=self.request.user)
        return preferences


class DeleteDataView(APIView):
    """POST /api/accounts/delete-data/ {"password": "..."}: erase the user's data, keep the account.

    Throttled hard (the "destructive" scope, per user) so it cannot be used to guess the
    password either: wrong attempts count too.
    """

    throttle_scope = "destructive"

    def post(self, request):
        serializer = ConfirmPasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            counts = delete_user_data(request.user)
        except ProtectedError:
            # An import added a transaction while we were erasing. Nothing was deleted.
            return Response(
                {"detail": "Your data changed during the erase. Nothing was deleted. Try again."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(counts)


class DeleteAccountView(APIView):
    """POST /api/accounts/delete-account/ {"password": "..."}: delete the account and everything
    it has (accounts.services.delete_account). Signs the browser out.

    Same guards as delete-data: the password again, and the "destructive" throttle (the two share
    it). Allowed without a date of birth on file: leaving must always be possible.
    """

    throttle_scope = "destructive"
    age_check_exempt = True

    def post(self, request):
        serializer = ConfirmPasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            delete_account(request.user)
        except ProtectedError:
            # An import added a transaction while we were deleting. Nothing was deleted.
            return Response(
                {"detail": "Your data changed during the delete. Nothing was deleted. Try again."},
                status=status.HTTP_409_CONFLICT,
            )
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_auth_cookies(response)
        return response


class BirthDateView(APIView):
    """POST /api/accounts/birth-date/ {"birth_date": "YYYY-MM-DD"}: for accounts made before dates
    of birth were asked for. 18+ only, and set once: changing it is not self-service."""

    throttle_scope = "auth"  # 5/min: a date is not something to guess at
    age_check_exempt = True

    def post(self, request):
        if request.user.birth_date_enc is not None:
            return Response(
                {"detail": "Your date of birth is already on file."},
                status=status.HTTP_409_CONFLICT,
            )
        serializer = BirthDateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_birth_date(request.user, serializer.validated_data["birth_date"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutView(APIView):
    """Revoke the login and delete this browser's vault session, so its copy of the data key is
    gone: the data is locked again until the next login (Phase 12.1, D4)."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        enforce_csrf(request)
        raw_refresh = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except TokenError:
                pass  # already expired/invalid/blacklisted: logout must still succeed
        close_session(request.COOKIES.get(settings.AUTH_COOKIE_VAULT))
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_auth_cookies(response)
        return response


class ChangePasswordView(APIView):
    """POST /api/accounts/change-password/ {"current_password", "new_password"} (Phase 12.1, D12).

    The data key is re-locked with the new password, so the old one stops opening it. Every other
    browser's vault session is deleted (they must sign in again); this one stays signed in. The
    recovery key is unchanged."""

    throttle_scope = "auth"  # 5/min: the current password must not be guessable here

    def post(self, request):
        user = request.user
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        new_password = serializer.validated_data["new_password"]
        with transaction.atomic():  # the lock and the password change together, or not at all
            set_password_lock(user, unlocked_key(user), new_password)
            user.set_password(new_password)
            user.save(update_fields=["password"])
            close_other_sessions(user, request.COOKIES.get(settings.AUTH_COOKIE_VAULT))
        return Response(status=status.HTTP_204_NO_CONTENT)


class RecoverView(APIView):
    """POST /api/accounts/recover/ {"email", "recovery_key", "new_password"}: forgot password
    (Phase 12.1, D13). Open to anyone, throttled hard.

    The recovery key opens the data key, which is then locked with the new password and given a
    NEW recovery key (the one just typed may have been seen). Every session is closed and every
    refresh token revoked. A wrong email and a wrong key get the same answer, so this never says
    who has an account."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        enforce_csrf(request)  # Phase 12.2, D1
        serializer = RecoverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if account_is_locked(data["email"]):  # Phase 12.2, D4: shared with failed logins
            return too_many_failures()
        user = User.objects.filter(email__iexact=User.objects.normalize_email(data["email"])).first()
        try:
            if user is None or not user.is_active:
                raise WrongSecret
            dek = unlock_with_recovery_key(user, data["recovery_key"])
        except WrongSecret:
            record_failure(data["email"])
            return Response(
                {"code": "recovery_failed", "detail": "That email and recovery key don't match."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer.check_new_password(user)

        with transaction.atomic():
            set_password_lock(user, dek, data["new_password"])
            recovery_key = replace_recovery_key(user, dek)
            user.set_password(data["new_password"])
            user.save(update_fields=["password"])
            close_all_sessions(user)
            revoke_refresh_tokens(user)
        return Response({"recovery_key": recovery_key})


class RecoveryKeyView(APIView):
    """POST /api/accounts/recovery-key/ {"password"}: a new recovery key, for a user who lost theirs
    but can still sign in (Phase 12.1, D14). The old one stops working."""

    throttle_scope = "destructive"  # rare, and the password must not be guessable here

    def post(self, request):
        serializer = ConfirmPasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        recovery_key = replace_recovery_key(request.user, unlocked_key(request.user))
        return Response({"recovery_key": recovery_key})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """GET this once so the browser receives the csrftoken cookie."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "CSRF cookie set."})

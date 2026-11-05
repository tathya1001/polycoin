from rest_framework.permissions import BasePermission


class AgeConfirmed(BasePermission):
    """Only adults may use MoneyAngle, so a signed-in user needs a date of birth on file before
    any other endpoint answers. It was checked to be 18+ when it was given.

    Accounts made before dates of birth were asked for have none. They get 403
    {"code": "birth_date_required"}, and the app shows its "confirm your date of birth" screen.
    The views that screen needs opt out with `age_check_exempt = True`: who am I, preferences
    (the look), giving the date, and deleting the account (leaving must always be possible).

    In DEFAULT_PERMISSION_CLASSES after IsAuthenticated, so anonymous requests still get 401.
    """

    message = {"code": "birth_date_required", "detail": "Confirm your date of birth to continue."}

    def has_permission(self, request, view):
        if getattr(view, "age_check_exempt", False):
            return True
        user = request.user
        return not user.is_authenticated or user.birth_date_enc is not None

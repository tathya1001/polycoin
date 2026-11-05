from django.urls import path

from . import views

urlpatterns = [
    path("csrf/", views.CsrfView.as_view(), name="csrf"),
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("preferences/", views.PreferencesView.as_view(), name="preferences"),
    path("delete-data/", views.DeleteDataView.as_view(), name="delete-data"),
    path("delete-account/", views.DeleteAccountView.as_view(), name="delete-account"),
    path("birth-date/", views.BirthDateView.as_view(), name="birth-date"),
    path("change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("recover/", views.RecoverView.as_view(), name="recover"),
    path("recovery-key/", views.RecoveryKeyView.as_view(), name="recovery-key"),
]

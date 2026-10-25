from django.urls import path

from .views import DownloadView, RestoreView

urlpatterns = [
    path("backup/", DownloadView.as_view()),
    path("backup/restore/", RestoreView.as_view()),
]

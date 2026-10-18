from django.urls import path

from .views import ApplyView, PrepareView

urlpatterns = [
    path("ai/categorize/prepare/", PrepareView.as_view()),
    path("ai/categorize/apply/", ApplyView.as_view()),
]

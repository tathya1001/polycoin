from django.urls import path

from .views import ApplyView, ModelsView, PrepareView, PreviewView

urlpatterns = [
    path("ai/models/", ModelsView.as_view()),
    path("ai/categorize/prepare/", PrepareView.as_view()),
    path("ai/categorize/preview/", PreviewView.as_view()),
    path("ai/categorize/apply/", ApplyView.as_view()),
]

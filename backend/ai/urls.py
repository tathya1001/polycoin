from django.urls import path

from . import rag_views
from .views import ApplyView, PrepareView

urlpatterns = [
    path("ai/categorize/prepare/", PrepareView.as_view()),
    path("ai/categorize/apply/", ApplyView.as_view()),
    # "Ask your transactions". rag_views loads langchain-core, numpy and rank-bm25; config/wsgi.py
    # loads this URLconf at boot, so no user's request pays for that.
    path("ai/rag/status/", rag_views.StatusView.as_view()),
    path("ai/rag/pending/", rag_views.PendingView.as_view()),
    path("ai/rag/vectors/", rag_views.VectorsView.as_view()),
    path("ai/rag/ask/", rag_views.AskView.as_view()),
    path("ai/rag/index/", rag_views.IndexView.as_view()),
]

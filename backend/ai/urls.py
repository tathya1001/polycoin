from django.urls import path

from . import agent_views, rag_views
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
    # The AI panel builder. agent_views loads LangGraph; like the RAG views, it is loaded at
    # boot through this URLconf.
    path("ai/agent/status/", agent_views.StatusView.as_view()),
    path("ai/agent/turn/", agent_views.TurnView.as_view()),
    path("ai/agent/step/", agent_views.StepView.as_view()),
]

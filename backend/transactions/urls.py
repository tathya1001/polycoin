from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    BulkLinkView,
    ImportPreviewView,
    ImportView,
    LinkDetailView,
    LinkView,
    TransactionViewSet,
    TransferSuggestionsView,
)

router = SimpleRouter()
router.register("transactions", TransactionViewSet, basename="transaction")

# Before the router URLs, or "import" would be read as a transaction id.
urlpatterns = [
    path("transactions/import/preview/", ImportPreviewView.as_view()),
    path("transactions/import/", ImportView.as_view()),
    path("transactions/links/", LinkView.as_view()),
    path("transactions/links/bulk/", BulkLinkView.as_view()),
    path("transactions/links/<uuid:pk>/", LinkDetailView.as_view()),
    path("transactions/transfer-suggestions/", TransferSuggestionsView.as_view()),
    *router.urls,
]

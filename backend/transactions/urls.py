from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ImportPreviewView, ImportView, TransactionViewSet

router = SimpleRouter()
router.register("transactions", TransactionViewSet, basename="transaction")

# Before the router URLs, or "import" would be read as a transaction id.
urlpatterns = [
    path("transactions/import/preview/", ImportPreviewView.as_view()),
    path("transactions/import/", ImportView.as_view()),
    *router.urls,
]

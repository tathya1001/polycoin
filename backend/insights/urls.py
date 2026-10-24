from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import DashboardViewSet, FieldsView, QueryView, RowsView

router = SimpleRouter()
router.register("dashboards", DashboardViewSet, basename="dashboard")

urlpatterns = [
    path("insights/fields/", FieldsView.as_view()),
    path("insights/query/", QueryView.as_view()),
    path("insights/rows/", RowsView.as_view()),
] + router.urls

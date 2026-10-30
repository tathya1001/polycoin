from rest_framework.routers import SimpleRouter

from .views import DataSourceViewSet

router = SimpleRouter()
router.register("data-sources", DataSourceViewSet, basename="data-source")

urlpatterns = router.urls

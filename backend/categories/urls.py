from rest_framework.routers import SimpleRouter

from .views import CategoryViewSet

router = SimpleRouter()
router.register("categories", CategoryViewSet, basename="category")
urlpatterns = router.urls

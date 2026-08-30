from rest_framework.routers import DefaultRouter

from .views import BlobViewSet

router = DefaultRouter()
router.register("blobs", BlobViewSet, basename="blob")

urlpatterns = router.urls

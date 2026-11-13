from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import IngestionBatchViewSet, IngestionJobViewSet

router = DefaultRouter()
router.register(r'jobs', IngestionJobViewSet, basename='job')
router.register(r'batches', IngestionBatchViewSet, basename='batch')

urlpatterns = [
    path('', include(router.urls)),
]

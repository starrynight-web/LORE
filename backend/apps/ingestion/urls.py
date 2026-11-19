from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import IngestionBatchViewSet, IngestionJobViewSet, test_extractor_llm_connection

router = DefaultRouter()
router.register(r'jobs', IngestionJobViewSet, basename='job')
router.register(r'batches', IngestionBatchViewSet, basename='batch')

urlpatterns = [
    path('test-extractor-llm/', test_extractor_llm_connection, name='test-extractor-llm'),
    path('', include(router.urls)),
]

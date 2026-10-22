from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import IngestionJobViewSet

router = DefaultRouter()
router.register(r'jobs', IngestionJobViewSet, basename='job')

urlpatterns = [
    path('', include(router.urls)),
]

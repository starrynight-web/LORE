from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ReviewQueueViewSet, ConflictViewSet

router = DefaultRouter()
router.register(r'review', ReviewQueueViewSet, basename='review')
router.register(r'conflicts', ConflictViewSet, basename='conflict')

urlpatterns = [
    path('', include(router.urls)),
]

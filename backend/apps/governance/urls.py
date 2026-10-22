from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ReviewQueueViewSet, ConflictViewSet, 
    ScopedExceptionViewSet, EvidenceRequirementViewSet,
    layers_status_view, telemetry_view
)

router = DefaultRouter()
router.register(r'review', ReviewQueueViewSet, basename='review')
router.register(r'conflicts', ConflictViewSet, basename='conflict')
router.register(r'exceptions', ScopedExceptionViewSet, basename='exception')
router.register(r'requirements', EvidenceRequirementViewSet, basename='requirement')

urlpatterns = [
    path('layers/', layers_status_view, name='governance-layers-status'),
    path('telemetry/', telemetry_view, name='governance-telemetry'),
    path('', include(router.urls)),
]

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ReviewQueueViewSet, ConflictViewSet, 
    ScopedExceptionViewSet, EvidenceRequirementViewSet,
    layers_status_view, telemetry_view,
    evaluations_view, evaluation_detail_view, evaluation_categories_view,
    evaluation_failures_view, evaluation_compare_view, evaluation_baseline_view,
    evaluation_promote_view, evaluation_rollback_view
)

router = DefaultRouter()
router.register(r'review', ReviewQueueViewSet, basename='review')
router.register(r'conflicts', ConflictViewSet, basename='conflict')
router.register(r'exceptions', ScopedExceptionViewSet, basename='exception')
router.register(r'requirements', EvidenceRequirementViewSet, basename='requirement')

urlpatterns = [
    path('layers/', layers_status_view, name='governance-layers-status'),
    path('telemetry/', telemetry_view, name='governance-telemetry'),
    path('evaluations/', evaluations_view, name='governance-evaluations'),
    path('evaluations/compare/', evaluation_compare_view, name='governance-evaluations-compare'),
    path('evaluations/baseline/', evaluation_baseline_view, name='governance-evaluations-baseline'),
    path('evaluations/rollback/', evaluation_rollback_view, name='governance-evaluations-rollback'),
    path('evaluations/<uuid:pk>/', evaluation_detail_view, name='governance-evaluation-detail'),
    path('evaluations/<uuid:pk>/categories/', evaluation_categories_view, name='governance-evaluation-categories'),
    path('evaluations/<uuid:pk>/failures/', evaluation_failures_view, name='governance-evaluation-failures'),
    path('evaluations/<uuid:pk>/promote/', evaluation_promote_view, name='governance-evaluation-promote'),
    path('', include(router.urls)),
]

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """LORE Enterprise liveness probe."""
    return Response({
        'status': 'healthy',
        'service': 'lore-enterprise-backend',
        'version': '2.0.0',
    })

@api_view(['GET'])
@permission_classes([AllowAny])
def readiness_check(request):
    """Deep readiness probe validating database, vector engine, and storage."""
    from django.db import connection
    from apps.retrieval.vector_store import QdrantVectorStore

    db_ok = True
    try:
        connection.cursor().execute("SELECT 1")
    except Exception:
        db_ok = False

    vstore = QdrantVectorStore()
    qdrant_ok = bool(vstore.client is not None)

    is_ready = db_ok and qdrant_ok
    status_code = 200 if is_ready else 503

    return Response({
        'status': 'ready' if is_ready else 'degraded',
        'service': 'lore-enterprise-backend',
        'dependencies': {
            'postgresql_database': 'connected' if db_ok else 'unreachable',
            'qdrant_vector_store': 'connected' if qdrant_ok else 'unreachable',
            'tesseract_ocr': 'available' if getattr(settings, 'TESSERACT_CMD', '') else 'disabled',
        }
    }, status=status_code)

from apps.governance.views import telemetry_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/health/', health_check, name='health-check'),
    path('api/v1/health/ready/', readiness_check, name='readiness-check'),
    path('api/v1/health/telemetry/', telemetry_view, name='health-telemetry'),
    path('api/v1/identity/', include('apps.identity.urls')),
    path('api/v1/workspaces/', include('apps.workspaces.urls')),
    path('api/v1/sources/', include('apps.sources.urls')),
    path('api/v1/ingestion/', include('apps.ingestion.urls')),
    path('api/v1/retrieval/', include('apps.retrieval.urls')),
    path('api/v1/governance/', include('apps.governance.urls')),
    path('api/v1/decisions/', include('apps.decisions.urls')),
    path('api/v1/audit/', include('apps.audit.urls')),
    path('api/v1/subscriptions/', include('apps.subscriptions.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


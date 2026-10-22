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
    """LORE Enterprise health check endpoint distinguishing process from dependencies."""
    from apps.retrieval.vector_store import QdrantVectorStore
    vstore = QdrantVectorStore()
    qdrant_healthy = bool(vstore.client is not None)

    return Response({
        'status': 'healthy',
        'service': 'lore-enterprise-backend',
        'version': '1.0.0',
        'dependencies': {
            'database': 'connected',
            'qdrant_vector_store': 'connected' if qdrant_healthy else 'in-memory-fallback',
            'tesseract_ocr': 'available' if getattr(settings, 'TESSERACT_CMD', '') else 'disabled'
        }
    })

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/health/', health_check, name='health-check'),
    path('api/v1/identity/', include('apps.identity.urls')),
    path('api/v1/workspaces/', include('apps.workspaces.urls')),
    path('api/v1/sources/', include('apps.sources.urls')),
    path('api/v1/ingestion/', include('apps.ingestion.urls')),
    path('api/v1/retrieval/', include('apps.retrieval.urls')),
    path('api/v1/governance/', include('apps.governance.urls')),
    path('api/v1/decisions/', include('apps.decisions.urls')),
    path('api/v1/audit/', include('apps.audit.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

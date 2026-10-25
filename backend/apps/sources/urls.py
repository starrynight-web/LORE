from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SourceDocumentViewSet, ZipImportViewSet

router = DefaultRouter()
router.register(r'documents', SourceDocumentViewSet, basename='document')
router.register(r'zip-imports', ZipImportViewSet, basename='zip-import')

urlpatterns = [
    path('', include(router.urls)),
]


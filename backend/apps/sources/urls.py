from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SourceDocumentViewSet

router = DefaultRouter()
router.register(r'documents', SourceDocumentViewSet, basename='document')

urlpatterns = [
    path('', include(router.urls)),
]

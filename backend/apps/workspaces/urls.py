from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import WorkspaceViewSet, CollectionViewSet

router = DefaultRouter()
router.register(r'workspaces', WorkspaceViewSet, basename='workspace')
router.register(r'collections', CollectionViewSet, basename='collection')

urlpatterns = [
    path('', include(router.urls)),
]

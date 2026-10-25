from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DecisionRecordViewSet, ConversationViewSet

router = DefaultRouter()
router.register(r'history', DecisionRecordViewSet, basename='decision')
router.register(r'conversations', ConversationViewSet, basename='conversation')

urlpatterns = [
    path('', include(router.urls)),
]

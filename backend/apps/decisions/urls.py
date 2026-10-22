from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DecisionRecordViewSet

router = DefaultRouter()
router.register(r'history', DecisionRecordViewSet, basename='decision')

urlpatterns = [
    path('', include(router.urls)),
]

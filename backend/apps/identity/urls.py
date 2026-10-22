from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import register_view, login_view, me_view, OrganizationViewSet

router = DefaultRouter()
router.register(r'organizations', OrganizationViewSet, basename='organization')

urlpatterns = [
    path('register/', register_view, name='register'),
    path('login/', login_view, name='login'),
    path('me/', me_view, name='me'),
    path('', include(router.urls)),
]

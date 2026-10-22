from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import register_view, login_view, logout_view, me_view, accept_invitation_view, OrganizationViewSet

router = DefaultRouter()
router.register(r'organizations', OrganizationViewSet, basename='organization')

urlpatterns = [
    path('register/', register_view, name='register'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('me/', me_view, name='me'),
    path('invitations/accept/', accept_invitation_view, name='accept-invitation'),
    path('', include(router.urls)),
]

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    register_view, login_view, logout_view, me_view, accept_invitation_view, OrganizationViewSet,
    scim_users_view, scim_user_detail_view, scim_groups_view, scim_group_sync_view
)

router = DefaultRouter()
router.register(r'organizations', OrganizationViewSet, basename='organization')

urlpatterns = [
    path('register/', register_view, name='register'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('me/', me_view, name='me'),
    path('invitations/accept/', accept_invitation_view, name='accept-invitation'),
    # SCIM 2.0 Directory Integration (P4 §22)
    path('scim/v2/Users', scim_users_view, name='scim-users'),
    path('scim/v2/Users/<int:user_id>', scim_user_detail_view, name='scim-user-detail'),
    path('scim/v2/Groups', scim_groups_view, name='scim-groups'),
    path('scim/v2/Groups/<str:workspace_id>', scim_group_sync_view, name='scim-group-sync'),
    path('', include(router.urls)),
]

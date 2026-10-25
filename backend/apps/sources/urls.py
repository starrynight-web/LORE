from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SourceDocumentViewSet, ZipImportViewSet
from .email_views import EmailConnectionViewSet, EmailOAuthAuthorizeView, EmailOAuthCallbackView

router = DefaultRouter()
router.register(r'documents', SourceDocumentViewSet, basename='document')
router.register(r'zip-imports', ZipImportViewSet, basename='zip-import')
router.register(r'email/connections', EmailConnectionViewSet, basename='email-connection')

urlpatterns = [
    path('email/oauth/authorize/', EmailOAuthAuthorizeView.as_view(), name='email-oauth-authorize'),
    path('email/oauth/callback/', EmailOAuthCallbackView.as_view(), name='email-oauth-callback'),
    path('', include(router.urls)),
]



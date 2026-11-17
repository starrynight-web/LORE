from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SourceDocumentViewSet,
    ZipImportViewSet,
    connector_status_view,
    trigger_connector_sync_view,
    connector_webhook_view,
    web_scraper_crawl_view,
)
from .email_views import EmailConnectionViewSet, EmailOAuthAuthorizeView, EmailOAuthCallbackView

router = DefaultRouter()
router.register(r'documents', SourceDocumentViewSet, basename='document')
router.register(r'zip-imports', ZipImportViewSet, basename='zip-import')
router.register(r'email/connections', EmailConnectionViewSet, basename='email-connection')

urlpatterns = [
    path('connectors/status/', connector_status_view, name='connector-status'),
    path('connectors/trigger-sync/', trigger_connector_sync_view, name='connector-trigger-sync'),
    path('connectors/webhook/<str:connector_type>/', connector_webhook_view, name='connector-webhook'),
    path('scraper/crawl/', web_scraper_crawl_view, name='web-scraper-crawl'),
    path('email/oauth/authorize/', EmailOAuthAuthorizeView.as_view(), name='email-oauth-authorize'),
    path('email/oauth/callback/', EmailOAuthCallbackView.as_view(), name='email-oauth-callback'),
    path('', include(router.urls)),
]



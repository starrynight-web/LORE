from django.urls import path
from .views import (
    docs_manifest_view,
    docs_settings_update_view,
    docs_content_update_view,
    docs_telemetry_view,
    docs_export_view,
)

urlpatterns = [
    path('', docs_manifest_view, name='docs-manifest'),
    path('settings/', docs_settings_update_view, name='docs-settings-update'),
    path('content/', docs_content_update_view, name='docs-content-update'),
    path('telemetry/', docs_telemetry_view, name='docs-telemetry'),
    path('export/', docs_export_view, name='docs-export'),
]

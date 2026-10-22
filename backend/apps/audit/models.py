import uuid
from django.db import models
from django.contrib.auth.models import User
from apps.identity.models import Organization
from apps.workspaces.models import Workspace

class AuditEvent(models.Model):
    EVENT_TYPES = [
        ('document_uploaded', 'Document Uploaded'),
        ('ocr_completed', 'OCR Extraction Completed'),
        ('ingestion_completed', 'Ingestion Pipeline Completed'),
        ('retrieval_query', 'Knowledge Retrieval Executed'),
        ('decision_recorded', 'Decision Recorded'),
        ('conflict_resolved', 'Conflict Resolved'),
        ('item_quarantined', 'Item Quarantined'),
        ('item_promoted', 'Item Promoted to Live Stable'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True, related_name='audit_events')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, null=True, blank=True, related_name='audit_events')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_events')

    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    target_type = models.CharField(max_length=50, blank=True, default='')
    target_id = models.CharField(max_length=100, blank=True, default='')
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.event_type}] by {self.user} on {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"

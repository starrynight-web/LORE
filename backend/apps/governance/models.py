import uuid
from django.db import models
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument

class EvidenceRequirement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, null=True, blank=True, related_name='evidence_requirements')
    decision_type = models.CharField(max_length=100, db_index=True)
    evidence_type = models.CharField(max_length=100)
    is_mandatory = models.BooleanField(default=True)
    min_authority_level = models.PositiveSmallIntegerField(default=3)
    description = models.TextField(blank=True, default='')

    def __str__(self):
        return f"{self.decision_type} -> {self.evidence_type} (mandatory={self.is_mandatory})"

class ConflictRecord(models.Model):
    STATUS_CHOICES = [
        ('unresolved', 'Unresolved / Conflicting'),
        ('resolved_by_authority', 'Resolved by Authority Dominance'),
        ('human_overridden', 'Resolved by Human Reviewer'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='conflicts')
    source_a = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name='conflicts_as_a')
    source_b = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name='conflicts_as_b')
    claim_a = models.TextField()
    claim_b = models.TextField()
    resolution_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='unresolved')
    resolution_notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Conflict: {self.source_a.title} vs {self.source_b.title} [{self.resolution_status}]"

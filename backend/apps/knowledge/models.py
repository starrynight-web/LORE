import uuid
from django.db import models
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument, DocumentVersion

class DocumentChunk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='chunks')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='chunks')
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name='chunks')
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, null=True, blank=True, related_name='chunks')

    chunk_index = models.PositiveIntegerField()
    text = models.TextField()
    contextual_header = models.TextField(blank=True, default='')
    page_number = models.PositiveIntegerField(default=1)
    heading_path = models.CharField(max_length=500, blank=True, default='')
    char_offset_start = models.PositiveIntegerField(default=0)
    char_offset_end = models.PositiveIntegerField(default=0)
    token_count = models.PositiveIntegerField(default=0)

    # Vector store reference ID
    vector_id = models.CharField(max_length=64, blank=True, default='', db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['chunk_index']
        unique_together = ('document', 'chunk_index')

    def __str__(self):
        return f"{self.document.title} - Chunk {self.chunk_index} (Page {self.page_number})"

class KnowledgeItem(models.Model):
    ITEM_TYPES = [
        ('rule', 'Rule / Policy Directive'),
        ('skill', 'Skill / Procedure'),
        ('fact', 'Verified Fact'),
        ('exception', 'Scoped Exception'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft (Unverified)'),
        ('stable', 'Stable (Approved & Served Live)'),
        ('superseded', 'Superseded'),
        ('quarantined', 'Quarantined / Conflicting'),
        ('stale', 'Stale / Expired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='knowledge_items')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='knowledge_items')
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, null=True, blank=True, related_name='knowledge_items')
    source_chunk = models.ForeignKey(DocumentChunk, on_delete=models.SET_NULL, null=True, blank=True, related_name='extracted_items')

    item_type = models.CharField(max_length=20, choices=ITEM_TYPES, default='rule')
    code = models.CharField(max_length=50, blank=True, default='')  # e.g. POL-SEC-041
    statement = models.TextField()
    component = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='stable')
    confidence = models.FloatField(default=0.90)
    authority_level = models.PositiveSmallIntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.code or self.item_type}] {self.statement[:60]}... ({self.status})"

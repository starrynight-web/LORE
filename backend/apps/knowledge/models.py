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
    # Deterministic content hash for selective embedding reuse (SHA-256)
    content_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)

    # Structure & Evidence Preservation
    section_identifier = models.CharField(max_length=100, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)

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


class RelationshipType(models.TextChoices):
    APPLIES_TO = 'APPLIES_TO', 'Applies To'
    DEPENDS_ON = 'DEPENDS_ON', 'Depends On'
    REQUIRES = 'REQUIRES', 'Requires'
    SUPERSEDES = 'SUPERSEDES', 'Supersedes'
    CONFLICTS_WITH = 'CONFLICTS_WITH', 'Conflicts With'
    DERIVED_FROM = 'DERIVED_FROM', 'Derived From'
    OVERRIDES = 'OVERRIDES', 'Overrides'
    GOVERNED_BY = 'GOVERNED_BY', 'Governed By'


class RelationshipApprovalStatus(models.TextChoices):
    PENDING = 'pending_approval', 'Pending Approval'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'


class KnowledgeRelationship(models.Model):
    """
    Canonical typed relational edge layer for Governed GraphRAG (lore.md §5 & §7).
    Connects knowledge entities (documents, chunks, items) across verified semantic relationship types.
    Enforces strict tenant scoping, provenance tracking, temporal validity, and publication approval.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='knowledge_relationships')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='knowledge_relationships')

    # Source node identity
    source_document = models.ForeignKey(
        SourceDocument, on_delete=models.CASCADE, null=True, blank=True, related_name='outgoing_relationships'
    )
    source_chunk = models.ForeignKey(
        DocumentChunk, on_delete=models.CASCADE, null=True, blank=True, related_name='outgoing_relationships'
    )
    source_item = models.ForeignKey(
        KnowledgeItem, on_delete=models.CASCADE, null=True, blank=True, related_name='outgoing_relationships'
    )

    # Target node identity
    target_document = models.ForeignKey(
        SourceDocument, on_delete=models.CASCADE, null=True, blank=True, related_name='incoming_relationships'
    )
    target_chunk = models.ForeignKey(
        DocumentChunk, on_delete=models.CASCADE, null=True, blank=True, related_name='incoming_relationships'
    )
    target_item = models.ForeignKey(
        KnowledgeItem, on_delete=models.CASCADE, null=True, blank=True, related_name='incoming_relationships'
    )

    relationship_type = models.CharField(max_length=40, choices=RelationshipType.choices, db_index=True)
    provenance = models.CharField(max_length=150, default='deterministic_rule')
    confidence = models.FloatField(default=1.0)
    approval_status = models.CharField(
        max_length=30, choices=RelationshipApprovalStatus.choices, default=RelationshipApprovalStatus.APPROVED, db_index=True
    )
    approved_by = models.CharField(max_length=150, blank=True, default='')

    # Valid-time bounds (lore.md L5 temporal validity)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'relationship_type', 'approval_status']),
            models.Index(fields=['source_document', 'relationship_type']),
            models.Index(fields=['target_document', 'relationship_type']),
        ]

    def is_temporally_valid(self, as_of=None) -> bool:
        """Evaluates whether the edge is active as of a given point-in-time."""
        from django.utils import timezone as tz
        from datetime import datetime, timezone
        if isinstance(as_of, str):
            from django.utils.dateparse import parse_datetime, parse_date
            parsed = parse_datetime(as_of)
            if not parsed:
                d = parse_date(as_of)
                if d:
                    parsed = datetime(d.year, d.month, d.day, 0, 0, 0)
            now = parsed or tz.now()
        elif isinstance(as_of, datetime):
            now = as_of
        else:
            now = tz.now()

        if tz.is_naive(now):
            now = tz.make_aware(now, timezone.utc)

        if self.valid_from:
            vf = self.valid_from if not tz.is_naive(self.valid_from) else tz.make_aware(self.valid_from, timezone.utc)
            if now < vf:
                return False

        if self.valid_until:
            vu = self.valid_until if not tz.is_naive(self.valid_until) else tz.make_aware(self.valid_until, timezone.utc)
            if now > vu:
                return False

        return True

    def __str__(self):
        src = self.source_document or self.source_chunk or self.source_item or "Unknown"
        tgt = self.target_document or self.target_chunk or self.target_item or "Unknown"
        return f"[{self.relationship_type}] {src} -> {tgt} ({self.approval_status})"

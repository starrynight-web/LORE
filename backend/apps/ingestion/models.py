import uuid
from django.db import models
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument

from django.conf import settings as django_settings


class IngestionBatch(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('partial_success', 'Partial Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='ingestion_batches')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='ingestion_batches')
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_ingestion_batches',
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='queued')
    total_files = models.PositiveIntegerField(default=0)
    visual_jobs_count = models.PositiveIntegerField(default=0)
    lightweight_jobs_count = models.PositiveIntegerField(default=0)
    completed_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    needs_review_count = models.PositiveIntegerField(default=0)
    quarantined_count = models.PositiveIntegerField(default=0)
    cancelled_count = models.PositiveIntegerField(default=0)
    skipped_duplicate_count = models.PositiveIntegerField(default=0)
    max_concurrent_visual = models.PositiveIntegerField(default=2)
    max_concurrent_lightweight = models.PositiveIntegerField(default=8)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ingestion_batches'
        ordering = ['-created_at']


class IngestionJob(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('extracting', 'Extracting Text & OCR'),
        ('normalizing', 'Normalizing Content & Formatting'),
        ('chunking', 'Structure-Aware Chunking'),
        ('embedding', 'Generating Vector Embeddings'),
        ('indexing', 'Indexing Graph & Vector Store'),
        ('ready', 'Completed & Ready'),
        ('failed', 'Processing Failed'),
        ('needs_review', 'Needs Review'),
        ('quarantined', 'Quarantined / Untrusted'),
        ('cancelled', 'Cancelled'),
    ]

    STAGES = [
        ('inspection', 'Inspection & Magic Byte Validation'),
        ('extraction', 'Document Extraction & OCR'),
        ('normalization', 'Phonetic & Structural Normalization'),
        ('chunking', 'Structure-Aware Chunking'),
        ('embedding', 'Vector Embedding Generation'),
        ('indexing', 'Dual Vector/Lexical Indexing'),
        ('completed', 'Pipeline Completed'),
        ('failed', 'Pipeline Failed'),
        ('cancelled', 'Cancelled'),
    ]

    WORKLOAD_CLASS_CHOICES = [
        ('visual', 'Visual / Heavy PDF & Image'),
        ('lightweight', 'Lightweight Native Office & Text'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name='ingestion_jobs')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='ingestion_jobs')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='ingestion_jobs')
    batch = models.ForeignKey(
        IngestionBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='jobs',
    )

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='queued')
    current_stage = models.CharField(max_length=30, choices=STAGES, default='inspection')
    workload_class = models.CharField(max_length=20, choices=WORKLOAD_CLASS_CHOICES, default='lightweight', db_index=True)
    queue_name = models.CharField(max_length=64, blank=True, default='')
    worker_id = models.CharField(max_length=128, blank=True, default='')
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, blank=True, default='', db_index=True)
    is_cancellation_requested = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    stage_timings = models.JSONField(default=dict, blank=True)
    pipeline_summary = models.JSONField(default=dict, blank=True)
    
    error_message = models.TextField(blank=True, default='')
    error_category = models.CharField(max_length=50, blank=True, default='')
    
    attempt_count = models.PositiveIntegerField(default=1)
    max_retries = models.PositiveIntegerField(default=3)
    
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Job {self.id} - {self.document.title} [{self.status}]"


class IngestionPipelineRun(models.Model):
    """
    Observable, sequential pipeline run tracking (Runs 1 to 4).
    Enforces strict prerequisites, persistent status, timestamps, attempt counters, and diagnostics.
    """
    STAGE_CHOICES = [
        ('run_1_ingestion', 'Run 1 — Initial Ingestion and Indexing'),
        ('run_2_quality', 'Run 2 — Quality Validation and Refinement'),
        ('run_3_retrieval', 'Run 3 — Retrieval Optimization'),
        ('run_4_decision', 'Run 4 — Evaluation and Improvement Decision'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('passed', 'Passed'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
        ('blocked', 'Blocked'),
        ('needs_review', 'Needs Human Review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(IngestionJob, on_delete=models.CASCADE, related_name='pipeline_runs')
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name='pipeline_runs')
    stage = models.CharField(max_length=40, choices=STAGE_CHOICES)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    attempt_count = models.PositiveIntegerField(default=1)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    diagnostics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        unique_together = ('job', 'stage')

    def __str__(self):
        return f"{self.job_id} - {self.stage} [{self.status}]"

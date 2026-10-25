import uuid
from django.db import models
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument

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
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name='ingestion_jobs')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='ingestion_jobs')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='ingestion_jobs')

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='queued')
    current_stage = models.CharField(max_length=30, choices=STAGES, default='inspection')
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

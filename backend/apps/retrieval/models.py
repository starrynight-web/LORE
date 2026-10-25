import uuid
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument
from apps.ingestion.models import IngestionJob

User = get_user_model()


class RetrievalConfiguration(models.Model):
    """
    Versioned, auditable retrieval parameter configuration for LORE Enterprise.
    Controls hybrid search weights, RRF k, candidate limits, reranking thresholds,
    and context token budgeting.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='retrieval_configurations'
    )
    version = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=150, default="Production Default Configuration")
    is_active = models.BooleanField(default=False, db_index=True)

    # Controlled Retrieval Parameters
    limit = models.PositiveIntegerField(
        default=8,
        help_text="Top-K candidates passed to downstream reranking and budgeting"
    )
    rrf_k = models.FloatField(
        default=60.0,
        help_text="Reciprocal Rank Fusion smoothing parameter (higher value dampens top rank outliers)"
    )
    min_relevance_threshold = models.FloatField(
        default=0.05,
        help_text="Minimum relevance score threshold for ContextReranker"
    )
    context_budget_tokens = models.PositiveIntegerField(
        default=800,
        help_text="Maximum token budget for assembled retrieval context"
    )

    # Graph Traversal Parameters
    enable_graph_expansion = models.BooleanField(default=True)
    graph_max_depth = models.PositiveIntegerField(default=2)
    graph_max_nodes = models.PositiveIntegerField(default=15)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_retrieval_configs'
    )
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-version', '-created_at']

    def __str__(self):
        ws_str = self.workspace.name if self.workspace else "Global"
        active_str = "[ACTIVE]" if self.is_active else ""
        return f"{self.name} v{self.version} ({ws_str}) {active_str}".strip()

    def to_dict(self):
        return {
            'id': str(self.id),
            'version': self.version,
            'name': self.name,
            'is_active': self.is_active,
            'limit': self.limit,
            'rrf_k': self.rrf_k,
            'min_relevance_threshold': self.min_relevance_threshold,
            'context_budget_tokens': self.context_budget_tokens,
            'enable_graph_expansion': self.enable_graph_expansion,
            'graph_max_depth': self.graph_max_depth,
            'graph_max_nodes': self.graph_max_nodes,
            'notes': self.notes
        }


class RetrievalOptimizationRun(models.Model):
    """
    Audit record of an evidence-driven retrieval optimization evaluation.
    Stores baseline metrics vs candidate metrics, query category breakdowns,
    and the final promotion/rollback decision.
    """
    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('improvement_proposed', 'Improvement Proposed'),
        ('retained_baseline', 'Retained Baseline'),
        ('blocked_missing_evaluation_dataset', 'Blocked: Missing Evaluation Dataset'),
        ('failed', 'Optimization Failed'),
    ]

    DECISION_CHOICES = [
        ('retained_baseline', 'Retained Baseline (No Justified Improvement)'),
        ('improvement_proposed', 'Improvement Proposed (Awaiting Review/Release)'),
        ('promoted', 'Promoted to Production'),
        ('rejected_regression', 'Rejected (Regressed Critical Metrics or Governance)'),
        ('blocked_no_dataset', 'Blocked (Missing Verified Evaluation Dataset)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='optimization_runs'
    )
    document = models.ForeignKey(
        SourceDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='optimization_runs'
    )
    job = models.ForeignKey(
        IngestionJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='retrieval_optimization_runs'
    )

    status = models.CharField(max_length=64, choices=STATUS_CHOICES, default='completed')
    baseline_config = models.ForeignKey(
        RetrievalConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='baseline_runs'
    )
    proposed_config = models.ForeignKey(
        RetrievalConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='proposed_runs'
    )
    rollback_config = models.ForeignKey(
        RetrievalConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rollback_runs'
    )

    # Empirical Evaluation Metrics
    baseline_metrics = models.JSONField(default=dict, blank=True)
    candidate_metrics = models.JSONField(default=dict, blank=True)
    category_breakdown = models.JSONField(default=dict, blank=True)

    decision = models.CharField(max_length=64, choices=DECISION_CHOICES, default='retained_baseline')
    decision_reason = models.TextField(blank=True, default='')
    eval_cases_count = models.PositiveIntegerField(default=0)
    eval_dataset_version = models.CharField(max_length=64, default='v1.0')

    is_promoted = models.BooleanField(default=False)
    promoted_at = models.DateTimeField(null=True, blank=True)
    promoted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='promoted_retrieval_runs'
    )

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"OptimizationRun {self.id} ({self.workspace.name}): {self.status} [{self.decision}]"

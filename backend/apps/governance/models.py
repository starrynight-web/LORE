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


class AccessLevel(models.TextChoices):
    PUBLIC = 'public', 'Public'
    INTERNAL = 'internal', 'Internal'
    RESTRICTED = 'restricted', 'Restricted'
    CONFIDENTIAL = 'confidential', 'Confidential'


class SourcePermission(models.Model):
    """
    L7 Permission Layer (lore.md §4 L7):
    Query-time authorization happening BEFORE context enters the model.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.OneToOneField(SourceDocument, on_delete=models.CASCADE, related_name='permissions')
    access_level = models.CharField(max_length=20, choices=AccessLevel.choices, default=AccessLevel.INTERNAL)
    allowed_roles = models.JSONField(default=list, blank=True)
    allowed_users = models.JSONField(default=list, blank=True)
    redaction_required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_user_permitted(self, user=None, user_role='member'):
        if self.access_level == AccessLevel.PUBLIC:
            return True
        if self.access_level == AccessLevel.INTERNAL:
            return user_role in ['workspace_admin', 'member', 'admin', 'compliance_auditor', 'owner']
        if self.access_level in [AccessLevel.RESTRICTED, AccessLevel.CONFIDENTIAL]:
            if user and getattr(user, 'is_superuser', False):
                return True
            if user and self.allowed_users and (getattr(user, 'username', '') in self.allowed_users or str(getattr(user, 'id', '')) in self.allowed_users):
                return True
            if self.allowed_roles and user_role in self.allowed_roles:
                return True
            if user_role in ['workspace_admin', 'owner']:
                return True
            return False
        return True

    def __str__(self):
        return f"Permission [{self.document.title}] - {self.access_level}"


class ScopedException(models.Model):
    """
    L4 Exception Layer (lore.md §4 L4):
    Scoped, time-bounded overrides.
    An exception applies only if every scope dimension matches and the query time falls within window.
    """
    SCOPE_TYPES = [
        ('department', 'Department / Business Unit'),
        ('project', 'Project / Repository'),
        ('data_type', 'Data Type / Classification'),
        ('vendor', 'Third-Party Vendor / Tool'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active & Effective'),
        ('expired', 'Expired'),
        ('revoked', 'Revoked by Human'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='exceptions')
    rule_code = models.CharField(max_length=100, db_index=True)
    scope_type = models.CharField(max_length=30, choices=SCOPE_TYPES, default='vendor')
    scope_value = models.CharField(max_length=255)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    justification = models.TextField()
    approved_by = models.CharField(max_length=150)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_currently_valid(self, as_of=None):
        import django.utils.timezone as tz
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

        if self.status != 'active':
            return False

        w_start = self.window_start
        if w_start:
            if tz.is_naive(w_start):
                w_start = tz.make_aware(w_start, timezone.utc)
            if now < w_start:
                return False

        w_end = self.window_end
        if w_end:
            if tz.is_naive(w_end):
                w_end = tz.make_aware(w_end, timezone.utc)
            if now > w_end:
                return False

        return True

    def __str__(self):
        return f"Exception [{self.rule_code}] for {self.scope_type}={self.scope_value} ({self.status})"


class EvaluationThresholdConfig(models.Model):
    """
    Configurable acceptance criteria for regression gating (Prompt 4 §7).
    Defines threshold boundaries to prevent scattering arbitrary constants in code.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name='eval_thresholds', null=True, blank=True)
    min_retrieval_precision = models.FloatField(default=0.80)
    min_retrieval_recall = models.FloatField(default=0.80)
    min_factual_correctness = models.FloatField(default=0.90)
    max_hallucination_rate = models.FloatField(default=0.00) # Zero tolerance
    max_leakage_rate = models.FloatField(default=0.00)       # Zero tolerance
    min_citation_accuracy = models.FloatField(default=0.95)
    max_permitted_regression = models.FloatField(default=0.05)
    max_query_latency_ms = models.IntegerField(default=3000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        ws_name = self.workspace.name if self.workspace else "Global Default"
        return f"Thresholds [{ws_name}] - Min Precision: {self.min_retrieval_precision}, Max Reg: {self.max_permitted_regression}"


class EndToEndEvaluationRun(models.Model):
    """
    Persistent record of an End-to-End Evaluation & Regression Gate run (Prompt 4 §2 & §8).
    Evaluates Runs 1-4, tracks answer grounding, governance, security, and baseline comparison.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('blocked', 'Blocked'),
        ('failed', 'Failed'),
    ]

    DECISION_CHOICES = [
        ('PASS', 'Pass - All Required Criteria Met'),
        ('PASS_WITH_LIMITATIONS', 'Pass with Limitations - Partial Evidence Coverage'),
        ('IMPROVEMENT_DEMONSTRATED', 'Improvement Demonstrated - Outperforms Baseline'),
        ('NO_CHANGE_JUSTIFIED', 'No Change Justified - Retain Current Configuration'),
        ('REGRESSION_DETECTED', 'Regression Detected - Metric Drop Exceeds Threshold'),
        ('BLOCKED', 'Blocked - Missing Prerequisites or Unverified Dataset'),
        ('FAILED', 'Failed - Execution Error or Critical Security Breach'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='e2e_evaluations')
    document = models.ForeignKey(SourceDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name='e2e_evaluations')
    job = models.ForeignKey('ingestion.IngestionJob', on_delete=models.SET_NULL, null=True, blank=True, related_name='e2e_evaluations')
    retrieval_config = models.ForeignKey('retrieval.RetrievalConfiguration', on_delete=models.SET_NULL, null=True, blank=True, related_name='e2e_evaluations')
    baseline_run = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='candidate_evaluations')

    evaluation_dataset_version = models.CharField(max_length=50, default='gold_evaluation_v1')
    embedding_model_identity = models.CharField(max_length=100, default='all-MiniLM-L6-v2')
    vector_index_identity = models.CharField(max_length=100, default='lore_chunks')
    app_version = models.CharField(max_length=50, default='2.0.0')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    decision = models.CharField(max_length=30, choices=DECISION_CHOICES, default='BLOCKED')
    decision_reason = models.TextField(blank=True, default='')

    is_approved_for_promotion = models.BooleanField(default=False)
    is_active_baseline = models.BooleanField(default=False)
    promoted_at = models.DateTimeField(null=True, blank=True)
    promoted_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='promoted_evaluations')

    eval_cases_total = models.IntegerField(default=0)
    eval_cases_passed = models.IntegerField(default=0)
    eval_cases_unverified = models.IntegerField(default=0)

    # Granular Metrics
    retrieval_metrics = models.JSONField(default=dict, blank=True)
    answer_metrics = models.JSONField(default=dict, blank=True)
    governance_metrics = models.JSONField(default=dict, blank=True)
    category_metrics = models.JSONField(default=dict, blank=True)
    baseline_comparison = models.JSONField(default=dict, blank=True)
    regressions_detected = models.JSONField(default=list, blank=True)
    proposed_actions = models.JSONField(default=list, blank=True)

    duration_ms = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"E2E Eval [{self.decision}] - {self.workspace.name} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"


class EvaluationFailureRecord(models.Model):
    """
    Root-cause grouped failure record for safe continuous improvement (Prompt 4 §9).
    """
    ROOT_CAUSE_CHOICES = [
        ('extraction', 'Extraction / OCR Issue'),
        ('chunking', 'Chunking / Boundary Issue'),
        ('metadata', 'Metadata / Version Issue'),
        ('retrieval', 'Retrieval / Ranking Issue'),
        ('governance', 'Governance / Security Issue'),
        ('generation', 'Answer Generation / Grounding Issue'),
        ('unverified_ground_truth', 'Unverified / Ambiguous Ground Truth'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evaluation_run = models.ForeignKey(EndToEndEvaluationRun, on_delete=models.CASCADE, related_name='failure_records')
    case_id = models.CharField(max_length=100)
    query = models.TextField()
    category = models.CharField(max_length=50)
    root_cause_group = models.CharField(max_length=30, choices=ROOT_CAUSE_CHOICES)
    failure_detail = models.TextField()
    expected_behavior = models.TextField()
    actual_behavior = models.TextField()
    proposed_remedy = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Failure [{self.root_cause_group}] - Case {self.case_id} ({self.evaluation_run.id})"


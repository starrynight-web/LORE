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
        from datetime import datetime
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
            now = tz.make_aware(now, tz.utc)

        if self.status != 'active':
            return False

        w_start = self.window_start
        if w_start:
            if tz.is_naive(w_start):
                w_start = tz.make_aware(w_start, tz.utc)
            if now < w_start:
                return False

        w_end = self.window_end
        if w_end:
            if tz.is_naive(w_end):
                w_end = tz.make_aware(w_end, tz.utc)
            if now > w_end:
                return False

        return True

    def __str__(self):
        return f"Exception [{self.rule_code}] for {self.scope_type}={self.scope_value} ({self.status})"


import uuid
from django.db import models
from django.contrib.auth.models import User
from apps.identity.models import Organization
from apps.workspaces.models import Workspace

class DecisionRecord(models.Model):
    STATE_CHOICES = [
        ('denied', 'denied (Stop)'),
        ('violation', 'violation (Stop)'),
        ('conflicting', 'conflicting (Ask User)'),
        ('insufficient', 'insufficient (Ask User + Missing List)'),
        ('abstain', 'abstain (Ask User)'),
        ('human_review', 'human_review (Escalate)'),
        ('qualified', 'qualified (Proceed & Cite)'),
        ('supported', 'supported (Proceed & Cite)'),
        ('no_knowledge', 'no_knowledge (Proceed)'),
    ]

    DIRECTIVE_CHOICES = [
        ('stop', 'stop'),
        ('ask_user', 'ask_user'),
        ('escalate', 'escalate'),
        ('proceed_and_cite', 'proceed_and_cite'),
        ('proceed', 'proceed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trace_id = models.CharField(max_length=64, db_index=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='decisions')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='decisions')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='decisions')

    query = models.TextField()
    decision_type = models.CharField(max_length=100, default='general_inquiry')
    state = models.CharField(max_length=30, choices=STATE_CHOICES)
    directive = models.CharField(max_length=30, choices=DIRECTIVE_CHOICES)
    
    answer_text = models.TextField(blank=True, default='')
    evidence_found = models.JSONField(default=list, blank=True)
    evidence_missing = models.JSONField(default=list, blank=True)
    conflicts_resolved = models.JSONField(default=list, blank=True)
    citations = models.JSONField(default=list, blank=True)
    
    token_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Decision {self.trace_id} - [{self.state}] {self.query[:40]}..."

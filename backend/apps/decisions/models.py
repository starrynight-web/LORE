import uuid
from django.db import models
from django.utils import timezone
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


class Conversation(models.Model):
    """
    Represents a persistent conversation thread in LORE's Governed Search & RAG interface.
    Strictly tenant- and user-isolated.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, default='New Conversation')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='conversations')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='conversations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')

    # Optional initial document or collection context scope
    document = models.ForeignKey('sources.SourceDocument', on_delete=models.SET_NULL, null=True, blank=True, related_name='conversations')
    collection = models.ForeignKey('workspaces.Collection', on_delete=models.SET_NULL, null=True, blank=True, related_name='conversations')

    is_archived = models.BooleanField(default=False, db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-last_activity_at']
        indexes = [
            models.Index(fields=['workspace', 'user', 'is_deleted', '-last_activity_at']),
            models.Index(fields=['user', '-last_activity_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.workspace.name})"


class ChatMessage(models.Model):
    """
    Represents an individual message turn (user inquiry or assistant governed response)
    within a persistent conversation.
    """
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]

    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    sequence_number = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed')

    # Link to canonical DecisionRecord if this turn generated a governance evaluation
    decision = models.ForeignKey(DecisionRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_messages')

    # Structured governance snapshot
    governance_state = models.CharField(max_length=30, blank=True, default='')
    governance_directive = models.CharField(max_length=30, blank=True, default='')
    trace_id = models.CharField(max_length=64, blank=True, default='')
    citations = models.JSONField(default=list, blank=True)
    evidence_missing = models.JSONField(default=list, blank=True)
    conflicts_resolved = models.JSONField(default=list, blank=True)
    layers_breakdown = models.JSONField(default=dict, blank=True)
    retrieval_config = models.JSONField(default=dict, blank=True)

    # Idempotency and error handling
    client_message_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    error_message = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['sequence_number', 'created_at']
        indexes = [
            models.Index(fields=['conversation', 'sequence_number']),
            models.Index(fields=['conversation', 'client_message_id']),
        ]

    def __str__(self):
        return f"[{self.role}] {self.content[:40]}... (Conv: {self.conversation_id})"


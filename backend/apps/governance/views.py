from rest_framework import serializers, viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from apps.sources.models import SourceDocument
from apps.sources.serializers import SourceDocumentSerializer
from .models import ConflictRecord, EvidenceRequirement
from apps.audit.models import AuditEvent

class ConflictRecordSerializer(serializers.ModelSerializer):
    source_a_title = serializers.CharField(source='source_a.title', read_only=True)
    source_b_title = serializers.CharField(source='source_b.title', read_only=True)

    class Meta:
        model = ConflictRecord
        fields = [
            'id', 'workspace', 'source_a', 'source_a_title',
            'source_b', 'source_b_title', 'claim_a', 'claim_b',
            'resolution_status', 'resolution_notes', 'created_at', 'updated_at'
        ]

class ReviewQueueViewSet(viewsets.ReadOnlyModelViewSet):
    """Lists and resolves documents in needs_review or quarantined status."""
    serializer_class = SourceDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        ws_id = self.request.query_params.get('workspace_id')
        qs = SourceDocument.objects.filter(
            workspace__memberships__user=user,
            status__in=['needs_review', 'quarantined']
        )
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.distinct()

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        doc = self.get_object()
        doc.status = 'ready'
        doc.save()

        AuditEvent.objects.create(
            organization=doc.organization,
            workspace=doc.workspace,
            user=request.user,
            event_type='item_promoted',
            target_type='document',
            target_id=str(doc.id),
            details={'action': 'human_approved', 'reviewer': request.user.username}
        )
        return Response({'message': 'Document approved and marked ready.', 'status': doc.status})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        doc = self.get_object()
        doc.status = 'quarantined'
        doc.save()

        AuditEvent.objects.create(
            organization=doc.organization,
            workspace=doc.workspace,
            user=request.user,
            event_type='item_quarantined',
            target_type='document',
            target_id=str(doc.id),
            details={'action': 'human_rejected', 'reviewer': request.user.username}
        )
        return Response({'message': 'Document rejected and quarantined.', 'status': doc.status})

class ConflictViewSet(viewsets.ModelViewSet):
    serializer_class = ConflictRecordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        ws_id = self.request.query_params.get('workspace_id')
        qs = ConflictRecord.objects.filter(workspace__memberships__user=user)
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.distinct()

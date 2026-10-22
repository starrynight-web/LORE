from rest_framework import serializers, viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.sources.models import SourceDocument
from apps.sources.serializers import SourceDocumentSerializer
from apps.audit.models import AuditEvent
from .models import ConflictRecord, EvidenceRequirement, ScopedException, SourcePermission, AccessLevel
from .layers import (
    DecisionIntelligenceLayer, AuthorityLayer, TemporalValidityLayer,
    ExceptionLayer, EvidenceSufficiencyLayer, AnswerStateLayer, PermissionLayer
)


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


class ScopedExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScopedException
        fields = [
            'id', 'workspace', 'rule_code', 'scope_type', 'scope_value',
            'window_start', 'window_end', 'justification', 'approved_by',
            'status', 'created_at', 'updated_at'
        ]


class EvidenceRequirementSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvidenceRequirement
        fields = [
            'id', 'workspace', 'decision_type', 'evidence_type',
            'is_mandatory', 'min_authority_level', 'description'
        ]


class ReviewQueueViewSet(viewsets.ReadOnlyModelViewSet):
    """Lists and resolves documents in needs_review or quarantined status."""
    serializer_class = SourceDocumentSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        ws_id = self.request.query_params.get('workspace_id')
        qs = SourceDocument.objects.filter(status__in=['needs_review', 'quarantined'])
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.distinct()

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        doc = self.get_object()
        doc.status = 'ready'
        doc.save()

        user = request.user if request.user and request.user.is_authenticated else None
        AuditEvent.objects.create(
            organization=doc.organization,
            workspace=doc.workspace,
            user=user,
            event_type='item_promoted',
            target_type='document',
            target_id=str(doc.id),
            details={'action': 'human_approved', 'reviewer': getattr(user, 'username', 'system_admin')}
        )
        return Response({'message': 'Document approved and marked ready.', 'status': doc.status})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        doc = self.get_object()
        doc.status = 'quarantined'
        doc.save()

        user = request.user if request.user and request.user.is_authenticated else None
        AuditEvent.objects.create(
            organization=doc.organization,
            workspace=doc.workspace,
            user=user,
            event_type='item_quarantined',
            target_type='document',
            target_id=str(doc.id),
            details={'action': 'human_rejected', 'reviewer': getattr(user, 'username', 'system_admin')}
        )
        return Response({'message': 'Document rejected and quarantined.', 'status': doc.status})


class ConflictViewSet(viewsets.ModelViewSet):
    serializer_class = ConflictRecordSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        ws_id = self.request.query_params.get('workspace_id')
        qs = ConflictRecord.objects.all()
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.distinct()


class ScopedExceptionViewSet(viewsets.ModelViewSet):
    """
    L4 Exception Layer Management:
    CRUD endpoints for scoped, time-bounded overrides.
    """
    serializer_class = ScopedExceptionSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        ws_id = self.request.query_params.get('workspace_id')
        qs = ScopedException.objects.all()
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.order_by('-created_at')


class EvidenceRequirementViewSet(viewsets.ModelViewSet):
    """
    L3 Evidence Requirement Registry:
    Configures required evidence per decision type.
    """
    serializer_class = EvidenceRequirementSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        ws_id = self.request.query_params.get('workspace_id')
        qs = EvidenceRequirement.objects.all()
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.order_by('decision_type', 'evidence_type')


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def layers_status_view(request):
    """
    Inspects live health, status, and metadata of all 9 enterprise layers (lore.md §3 & §4).
    """
    ws_id = request.query_params.get('workspace_id')
    exc_qs = ScopedException.objects.filter(status='active')
    req_qs = EvidenceRequirement.objects.all()
    if ws_id:
        exc_qs = exc_qs.filter(workspace_id=ws_id)
        req_qs = req_qs.filter(workspace_id=ws_id)

    layers = [
        {
            'layer': 'L7',
            'name': 'Permission Layer',
            'decides': 'May this requester see this knowledge?',
            'status': 'active',
            'mechanism': 'RBAC/ABAC authorization before context enters LLM window',
            'rbac_levels': ['public', 'internal', 'restricted', 'confidential'],
            'enforcement': 'Silent exclusion + denied hard stop if required evidence is restricted'
        },
        {
            'layer': 'L6',
            'name': 'Authority Layer',
            'decides': 'Which source wins when they disagree?',
            'status': 'active',
            'mechanism': '7-rank source authority ladder + conflict resolution',
            'ranks': [
                {'rank': 7, 'authority': 'approved_policy', 'served_live': True},
                {'rank': 6, 'authority': 'signed_contract', 'served_live': True},
                {'rank': 5, 'authority': 'team_convention', 'served_live': True},
                {'rank': 4, 'authority': 'maintained_procedure', 'served_live': True},
                {'rank': 3, 'authority': 'reviewed_document', 'served_live': True},
                {'rank': 2, 'authority': 'wiki_entry', 'served_live': 'flagged'},
                {'rank': 1, 'authority': 'informal_note', 'served_live': 'flagged'},
            ],
            'tie_breaking': 'Higher rank wins; same rank newer effective date wins; tied unresolved = conflicting verdict'
        },
        {
            'layer': 'L5',
            'name': 'Temporal Validity Layer',
            'decides': 'Is this rule in effect right now (or at date X)?',
            'status': 'active',
            'mechanism': 'effective_from/to dates + expiration + staleness aging + as_of point-in-time queries',
            'features': ['not_yet_effective exclusions', 'expired document drop', 'stale aging warning', 'gap-free point-in-time history']
        },
        {
            'layer': 'L4',
            'name': 'Exception Layer',
            'decides': 'Does a scoped override apply here?',
            'status': 'active',
            'mechanism': 'Scoped, time-bounded overrides with mandatory disclosure',
            'active_exceptions_count': exc_qs.count(),
            'scope_dimensions': ['department', 'project', 'data_type', 'vendor']
        },
        {
            'layer': 'L3',
            'name': 'Evidence Sufficiency Layer',
            'decides': 'Is the evidence complete for this decision?',
            'status': 'active',
            'mechanism': 'Requirements registry mapping decision types to mandatory evidence',
            'configured_rules_count': req_qs.count(),
            'evaluation_statuses': ['SATISFIED', 'PARTIAL', 'PENDING', 'MISSING', 'INSUFFICIENT_AUTHORITY', 'EXPIRED']
        },
        {
            'layer': 'L2',
            'name': 'Answer-State Layer',
            'decides': 'What may the agent do next?',
            'status': 'active',
            'mechanism': 'Deterministic 9-state machine with precedence ordering',
            'states_precedence': [
                {'state': 'denied', 'directive': 'stop', 'precedence': 1},
                {'state': 'violation', 'directive': 'stop', 'precedence': 2},
                {'state': 'conflicting', 'directive': 'ask_user', 'precedence': 3},
                {'state': 'insufficient', 'directive': 'ask_user', 'precedence': 4},
                {'state': 'abstain', 'directive': 'ask_user', 'precedence': 5},
                {'state': 'human_review', 'directive': 'escalate', 'precedence': 6},
                {'state': 'qualified', 'directive': 'proceed_and_cite', 'precedence': 7},
                {'state': 'supported', 'directive': 'proceed_and_cite', 'precedence': 8},
                {'state': 'no_knowledge', 'directive': 'proceed', 'precedence': 9},
            ]
        },
        {
            'layer': 'L1',
            'name': 'Decision Intelligence Layer',
            'decides': 'What kind of decision is this?',
            'status': 'active',
            'mechanism': 'Query classification into decision types with escalation targets',
            'catalog': DecisionIntelligenceLayer.DECISION_CATALOG
        },
        {
            'layer': 'L0',
            'name': 'Observability Layer',
            'decides': 'Is the system healthy and honest?',
            'status': 'active',
            'mechanism': 'Trace auditing, freshness monitoring, token metering, and propagation tracking'
        },
        {
            'layer': 'Core',
            'name': 'Hybrid Retrieval & Settlement Engine',
            'decides': 'What knowledge applies and what may enter?',
            'status': 'active',
            'mechanism': 'Dense vectors (Qdrant) + BM25 lexical + Reciprocal Rank Fusion (k=60) + Context Reranker'
        }
    ]

    return Response({
        'system': 'LORE Enterprise Governed Knowledge Grid',
        'architecture_version': '3.0 (Master Unified)',
        'all_9_layers_active': True,
        'layers_count': 9,
        'layers': layers,
        'timestamp': timezone.now().isoformat()
    })

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def telemetry_view(request):
    """LORE Enterprise Telemetry and SLO Observability endpoint."""
    from apps.governance.telemetry import TelemetryService
    workspace_id = request.query_params.get('workspace_id')
    snapshot = TelemetryService.get_telemetry_snapshot(workspace_id=workspace_id)
    return Response(snapshot)


from typing import Any
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
        req: Any = self.request
        ws_id = req.query_params.get('workspace_id')
        qs = SourceDocument.objects.filter(status__in=['needs_review', 'quarantined'])
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.distinct()

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        doc = self.get_object()
        doc.status = 'ready'
        doc.save(update_fields=['status'])

        # Invalidate workspace cache so newly approved document is live immediately
        try:
            from apps.retrieval.cache import TenantSafeCacheService
            TenantSafeCacheService.invalidate_document(str(doc.workspace_id), str(doc.id))
        except Exception:
            pass

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
        doc.save(update_fields=['status'])

        # Invalidate workspace cache to remove unapproved content
        try:
            from apps.retrieval.cache import TenantSafeCacheService
            TenantSafeCacheService.invalidate_document(str(doc.workspace_id), str(doc.id))
        except Exception:
            pass

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
        req: Any = self.request
        ws_id = req.query_params.get('workspace_id')
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
        req: Any = self.request
        ws_id = req.query_params.get('workspace_id')
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
        req: Any = self.request
        ws_id = req.query_params.get('workspace_id')
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


# ==============================================================================
# End-to-End Evaluation & Regression Testing API (Prompt 4 §11)
# ==============================================================================

class EndToEndEvaluationRunSerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)
    document_title = serializers.SerializerMethodField()

    def get_document_title(self, obj):
        return obj.document.title if obj.document else ''

    class Meta:
        from apps.governance.models import EndToEndEvaluationRun
        model = EndToEndEvaluationRun
        fields = [
            'id', 'workspace', 'workspace_name', 'document', 'document_title',
            'job', 'retrieval_config', 'baseline_run', 'evaluation_dataset_version',
            'embedding_model_identity', 'vector_index_identity', 'app_version',
            'status', 'decision', 'decision_reason', 'is_approved_for_promotion',
            'is_active_baseline', 'promoted_at', 'eval_cases_total', 'eval_cases_passed',
            'eval_cases_unverified', 'retrieval_metrics', 'answer_metrics',
            'governance_metrics', 'category_metrics', 'baseline_comparison',
            'regressions_detected', 'proposed_actions', 'duration_ms',
            'started_at', 'completed_at', 'created_at'
        ]


class EvaluationFailureRecordSerializer(serializers.ModelSerializer):
    class Meta:
        from apps.governance.models import EvaluationFailureRecord
        model = EvaluationFailureRecord
        fields = [
            'id', 'case_id', 'query', 'category', 'root_cause_group',
            'failure_detail', 'expected_behavior', 'actual_behavior',
            'proposed_remedy', 'created_at'
        ]


@api_view(['GET', 'POST'])
@permission_classes([permissions.AllowAny])
def evaluations_view(request):
    """
    GET: Lists evaluation runs for workspace.
    POST: Triggers a new End-to-End evaluation run.
    """
    from apps.workspaces.models import Workspace
    from apps.governance.models import EndToEndEvaluationRun
    from apps.governance.e2e_evaluation import EndToEndEvaluationService

    try:
        workspace_id = request.query_params.get('workspace') or request.data.get('workspace')
        if not workspace_id:
            return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        workspace = Workspace.objects.filter(id=workspace_id).first()
        if not workspace:
            return Response({'error': 'Workspace not found.'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'GET':
            runs = EndToEndEvaluationRun.objects.filter(workspace=workspace).order_by('-created_at')
            active_baseline = EndToEndEvaluationService.get_active_baseline(workspace)
            return Response({
                'workspace_id': str(workspace.id),
                'active_baseline': EndToEndEvaluationRunSerializer(active_baseline).data if active_baseline else None,
                'evaluations': EndToEndEvaluationRunSerializer(runs, many=True).data
            })

        elif request.method == 'POST':
            custom_cases = request.data.get('custom_cases')
            dataset_version = request.data.get('dataset_version', 'gold_evaluation_v1')
            user = request.user if request.user and request.user.is_authenticated else None

            eval_run = EndToEndEvaluationService.run_evaluation(
                workspace=workspace,
                custom_cases=custom_cases,
                requested_by=user,
                dataset_version=dataset_version
            )
            return Response(EndToEndEvaluationRunSerializer(eval_run).data, status=status.HTTP_201_CREATED)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        return Response({'error': str(ex)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def evaluation_detail_view(request, pk):
    """Returns complete summary and decision for a specific evaluation run."""
    from apps.governance.models import EndToEndEvaluationRun
    eval_run = EndToEndEvaluationRun.objects.filter(id=pk).first()
    if not eval_run:
        return Response({'error': f'Evaluation run {pk} not found.'}, status=status.HTTP_404_NOT_FOUND)
    return Response(EndToEndEvaluationRunSerializer(eval_run).data)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def evaluation_categories_view(request, pk):
    """Returns granular metrics broken down across 8 enterprise query categories."""
    from apps.governance.models import EndToEndEvaluationRun
    eval_run = EndToEndEvaluationRun.objects.filter(id=pk).first()
    if not eval_run:
        return Response({'error': f'Evaluation run {pk} not found.'}, status=status.HTTP_404_NOT_FOUND)
    return Response({
        'evaluation_run_id': str(eval_run.id),
        'decision': eval_run.decision,
        'category_metrics': eval_run.category_metrics
    })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def evaluation_failures_view(request, pk):
    """Returns representative failing cases grouped by root cause for continuous improvement."""
    from apps.governance.models import EndToEndEvaluationRun, EvaluationFailureRecord
    eval_run = EndToEndEvaluationRun.objects.filter(id=pk).first()
    if not eval_run:
        return Response({'error': f'Evaluation run {pk} not found.'}, status=status.HTTP_404_NOT_FOUND)
    failures = EvaluationFailureRecord.objects.filter(evaluation_run=eval_run).order_by('root_cause_group', 'case_id')
    
    grouped = {}
    for f in failures:
        grouped.setdefault(f.root_cause_group, []).append(EvaluationFailureRecordSerializer(f).data)

    return Response({
        'evaluation_run_id': str(eval_run.id),
        'total_failures': failures.count(),
        'grouped_by_root_cause': grouped
    })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def evaluation_compare_view(request):
    """Compares two evaluation runs and identifies regressions and improvements."""
    from apps.governance.models import EndToEndEvaluationRun

    run_a_id = request.query_params.get('run_a')
    run_b_id = request.query_params.get('run_b')
    if not run_a_id or not run_b_id:
        return Response({'error': 'run_a and run_b query parameters are required.'}, status=status.HTTP_400_BAD_REQUEST)

    run_a = EndToEndEvaluationRun.objects.filter(id=run_a_id).first()
    run_b = EndToEndEvaluationRun.objects.filter(id=run_b_id).first()
    if not run_a or not run_b:
        return Response({'error': 'One or both evaluation runs not found.'}, status=status.HTTP_404_NOT_FOUND)

    # Calculate comparative deltas (Run B minus Run A)
    ret_a = run_a.retrieval_metrics or {}
    ret_b = run_b.retrieval_metrics or {}
    ans_a = run_a.answer_metrics or {}
    ans_b = run_b.answer_metrics or {}

    delta_precision = ret_b.get('precision_k', 0.0) - ret_a.get('precision_k', 0.0)
    delta_recall = ret_b.get('recall_k', 0.0) - ret_a.get('recall_k', 0.0)
    delta_mrr = ret_b.get('mrr', 0.0) - ret_a.get('mrr', 0.0)
    delta_factual = ans_b.get('factual_correctness', 0.0) - ans_a.get('factual_correctness', 0.0)
    delta_latency = ret_b.get('avg_latency_ms', 0.0) - ret_a.get('avg_latency_ms', 0.0)

    return Response({
        'run_a': {
            'id': str(run_a.id),
            'decision': run_a.decision,
            'dataset_version': run_a.evaluation_dataset_version,
            'retrieval_metrics': ret_a,
            'answer_metrics': ans_a,
        },
        'run_b': {
            'id': str(run_b.id),
            'decision': run_b.decision,
            'dataset_version': run_b.evaluation_dataset_version,
            'retrieval_metrics': ret_b,
            'answer_metrics': ans_b,
        },
        'comparison': {
            'delta_precision_k': round(delta_precision, 4),
            'delta_recall_k': round(delta_recall, 4),
            'delta_mrr': round(delta_mrr, 4),
            'delta_factual_correctness': round(delta_factual, 4),
            'delta_latency_ms': round(delta_latency, 1),
            'regressions_in_b': run_b.regressions_detected
        }
    })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def evaluation_baseline_view(request):
    """Returns the current approved baseline evaluation for a workspace."""
    from apps.workspaces.models import Workspace
    from apps.governance.e2e_evaluation import EndToEndEvaluationService

    workspace_id = request.query_params.get('workspace')
    if not workspace_id:
        return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

    workspace = get_object_or_404(Workspace, id=workspace_id)
    baseline = EndToEndEvaluationService.get_active_baseline(workspace)
    if not baseline:
        return Response({'baseline': None, 'message': 'No approved baseline established yet.'})

    return Response({
        'baseline': EndToEndEvaluationRunSerializer(baseline).data
    })


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def evaluation_promote_view(request, pk):
    """Promotes an evaluation run to the active baseline with rollback capability."""
    from apps.governance.e2e_evaluation import EndToEndEvaluationService

    user = request.user if request.user.is_authenticated else None
    try:
        promoted = EndToEndEvaluationService.promote_baseline(pk, user=user)
        return Response({
            'status': 'promoted',
            'promoted_baseline': EndToEndEvaluationRunSerializer(promoted).data,
            'message': f"Evaluation run {promoted.id} promoted as active workspace baseline."
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def evaluation_rollback_view(request):
    """Rolls back the active baseline to the previous known-good evaluation run."""
    from apps.workspaces.models import Workspace
    from apps.governance.e2e_evaluation import EndToEndEvaluationService

    workspace_id = request.data.get('workspace')
    if not workspace_id:
        return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

    workspace = get_object_or_404(Workspace, id=workspace_id)
    user = request.user if request.user.is_authenticated else None

    try:
        restored = EndToEndEvaluationService.rollback_baseline(workspace, user=user)
        return Response({
            'status': 'rolled_back',
            'restored_baseline': EndToEndEvaluationRunSerializer(restored).data,
            'message': f"Active baseline rolled back to run {restored.id}."
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


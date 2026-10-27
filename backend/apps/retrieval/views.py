import time
import json
import urllib.request
import urllib.error
from django.conf import settings
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
import logging

from apps.workspaces.models import Workspace
from apps.decisions.models import DecisionRecord
from .services import HybridRetrievalService
from apps.decisions.engine import AnswerStateMachine
from apps.governance.layers import EnterpriseGovernanceEngine

logger = logging.getLogger(__name__)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def search_view(request):
    """Hybrid lexical + vector search across authorized workspace chunks."""
    workspace_id = request.data.get('workspace')
    query = request.data.get('query', '')
    collection_id = request.data.get('collection')
    document_id = request.data.get('document_id') or request.data.get('document')
    limit = int(request.data.get('limit', 8))

    if not workspace_id:
        return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not query.strip():
        return Response({'results': []})

    if request.user.is_authenticated:
        from django.db.models import Q
        workspace = Workspace.objects.filter(id=workspace_id).filter(
            Q(memberships__user=request.user) | Q(organization__memberships__user=request.user)
        ).distinct().first()
        if not workspace:
            return Response({'error': 'Workspace not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)
    else:
        workspace = get_object_or_404(Workspace, id=workspace_id)

    retrieval_service = HybridRetrievalService()
    results = retrieval_service.search(
        query=query,
        workspace_id=str(workspace.id),
        organization_id=str(workspace.organization.id),
        collection_id=collection_id,
        document_id=document_id,
        limit=limit
    )

    return Response({
        'query': query,
        'workspace': str(workspace.id),
        'results_count': len(results),
        'results': results,
        'diagnostics': retrieval_service.last_diagnostics
    })

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def governed_query_view(request):
    """
    Governed RAG Query Endpoint:
    Executes hybrid retrieval, evaluates through 9-state governance machine,
    resolves authority, checks sufficiency, and returns lore.result/1 envelope.
    """
    workspace_id = request.data.get('workspace')
    query = request.data.get('query', '')
    collection_id = request.data.get('collection')

    if not workspace_id:
        return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not query.strip():
        return Response({'error': 'Query text is required.'}, status=status.HTTP_400_BAD_REQUEST)

    if request.user.is_authenticated:
        from django.db.models import Q
        workspace = Workspace.objects.filter(id=workspace_id).filter(
            Q(memberships__user=request.user) | Q(organization__memberships__user=request.user)
        ).distinct().first()
        if not workspace:
            return Response({'error': 'Workspace not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)
        effective_user = request.user
    else:
        workspace = get_object_or_404(Workspace, id=workspace_id)
        first_mem = workspace.memberships.first()
        effective_user = first_mem.user if first_mem else None

    # Check SaaS Monthly Query Quotas
    from apps.subscriptions.services import QuotaEnforcementService
    try:
        QuotaEnforcementService.check_query_quota(workspace.organization)
    except Exception as e:
        return Response({'error': str(e), 'quota_exceeded': True}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    # Extract dynamic user Groq API configurations
    groq_api_key = (
        request.data.get('groq_api_key') or 
        request.headers.get('X-Groq-Api-Key') or 
        getattr(settings, 'GROQ_API_KEY', '')
    )
    llm_model = (
        request.data.get('llm_model') or 
        request.headers.get('X-LLM-Model') or 
        getattr(settings, 'GROQ_MODEL', 'gpt-oss-120B')
    )

    document_id = request.data.get('document_id') or request.data.get('document')
    as_of = request.data.get('as_of') or request.query_params.get('as_of')

    user_role = 'workspace_admin' if getattr(effective_user, 'is_staff', False) else 'member'
    bypass_cache = request.data.get('bypass_cache', False) or request.headers.get('Cache-Control') == 'no-cache'

    from apps.retrieval.cache import TenantSafeCacheService
    if not bypass_cache and not document_id:
        cached_envelope = TenantSafeCacheService.get(
            organization_id=str(workspace.organization.id),
            workspace_id=str(workspace.id),
            user_role=user_role,
            query=query,
            as_of=as_of
        )
        if cached_envelope:
            cached_envelope['cached'] = True
            return Response(cached_envelope)

    # 1. Retrieve Candidate Chunks (Scoped to Tenant, Collection, or specific PDF Document)
    retrieval_service = HybridRetrievalService()
    candidate_chunks = retrieval_service.search(
        query=query,
        workspace_id=str(workspace.id),
        organization_id=str(workspace.organization.id),
        collection_id=collection_id,
        document_id=document_id,
        limit=10,
        user=effective_user,
        user_role=user_role,
        as_of=as_of
    )

    # 2. Evaluate via Complete 9-Layer Enterprise Governance Engine (L7 -> L0)
    execution_mode = (
        request.data.get('execution_mode') or
        request.headers.get('X-Execution-Mode') or
        None
    )
    synthesis_mode = (
        request.data.get('synthesis_mode') or
        request.headers.get('X-Synthesis-Mode') or
        None
    )

    schema_version = (
        request.data.get('schema_version') or 
        request.headers.get('X-Schema-Version') or 
        'lore.result/1'
    )
    envelope = EnterpriseGovernanceEngine.evaluate(
        query=query,
        retrieved_chunks=candidate_chunks,
        workspace=workspace,
        user=effective_user,
        user_role=user_role,
        as_of=as_of,
        schema_version=schema_version,
        groq_api_key=groq_api_key,
        llm_model=llm_model,
        execution_mode=execution_mode,
        synthesis_mode=synthesis_mode
    )

    if not bypass_cache and not document_id:
        TenantSafeCacheService.set(
            organization_id=str(workspace.organization.id),
            workspace_id=str(workspace.id),
            user_role=user_role,
            query=query,
            envelope=envelope,
            as_of=as_of
        )

    # 3. Record Metered Query Usage
    try:
        from apps.subscriptions.services import QuotaEnforcementService
        QuotaEnforcementService.record_query(workspace.organization, workspace, envelope.get('token_count', 0))
    except Exception:
        pass

    # 4. Optional Persistent Chat Turn Recording
    conversation_id = request.data.get('conversation_id')
    save_conversation = request.data.get('save_conversation', False) or bool(conversation_id)

    if save_conversation and effective_user:
        try:
            from apps.decisions.models import Conversation, ChatMessage
            from apps.decisions.title_generator import generate_conversation_title

            conv = None
            if conversation_id:
                conv = Conversation.objects.filter(
                    id=conversation_id,
                    workspace=workspace,
                    is_deleted=False
                ).first()

            if not conv:
                conv_title = generate_conversation_title(query)
                conv = Conversation.objects.create(
                    organization=workspace.organization,
                    workspace=workspace,
                    user=effective_user,
                    title=conv_title,
                    document_id=document_id if document_id else None,
                    collection_id=collection_id if collection_id else None
                )

            last_msg = conv.messages.order_by('-sequence_number').first()
            seq = (last_msg.sequence_number + 1) if last_msg else 1

            client_msg_id = request.data.get('client_message_id', '')
            user_msg = ChatMessage.objects.create(
                conversation=conv,
                role='user',
                content=query,
                sequence_number=seq,
                client_message_id=client_msg_id or '',
                status='completed'
            )

            assistant_msg = ChatMessage.objects.create(
                conversation=conv,
                role='assistant',
                content=envelope.get('answer', ''),
                sequence_number=seq + 1,
                status='completed',
                governance_state=envelope.get('state', ''),
                governance_directive=envelope.get('directive', ''),
                trace_id=envelope.get('trace_id', ''),
                citations=envelope.get('citations', []),
                evidence_missing=envelope.get('evidence_missing', []),
                conflicts_resolved=envelope.get('conflicts_resolved', []),
                layers_breakdown=envelope.get('layers_breakdown', {}),
                retrieval_config={'document_id': document_id, 'collection_id': collection_id}
            )

            conv.last_activity_at = timezone.now()
            conv.save(update_fields=['last_activity_at', 'updated_at'])

            envelope['conversation_id'] = str(conv.id)
            envelope['conversation_title'] = conv.title
            envelope['user_message_id'] = str(user_msg.id)
            envelope['assistant_message_id'] = str(assistant_msg.id)
        except Exception as persist_err:
            logger.warning(f"Failed to persist conversation turn: {persist_err}")

    return Response(envelope)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def test_groq_api_view(request):
    """
    Validates user-supplied Groq API key and model connectivity.
    Default target model: gpt-oss-120B.
    """
    api_key = request.data.get('api_key', '').strip()
    model = request.data.get('model', 'gpt-oss-120B').strip()

    if not api_key:
        return Response({'error': 'Groq API key is required.'}, status=status.HTTP_400_BAD_REQUEST)

    t0 = time.time()
    try:
        # First verify authorization against models endpoint or test chat completion
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "LORE-Enterprise/2.0"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            models_list = [m.get('id') for m in data.get('data', [])]

        latency_ms = int((time.time() - t0) * 1000)
        has_exact_model = model in models_list

        return Response({
            'status': 'connected',
            'provider': 'groq',
            'requested_model': model,
            'model_available': has_exact_model,
            'models_count': len(models_list),
            'latency_ms': latency_ms,
            'anti_hallucination': 'active',
            'default_temperature': 0.0,
            'message': f"Successfully verified Groq connection in {latency_ms}ms. Ready for anti-hallucination inference."
        })
    except urllib.error.HTTPError as he:
        err_msg = f"Groq API error ({he.code}): {he.reason}"
        try:
            body = json.loads(he.read().decode('utf-8'))
            if 'error' in body and 'message' in body['error']:
                err_msg = body['error']['message']
        except Exception:
            pass
        return Response({'status': 'error', 'error': err_msg}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({'status': 'error', 'error': f"Connection failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST'])
@permission_classes([permissions.AllowAny])
def configurations_view(request):
    """
    GET: Returns active and historic retrieval configurations for workspace.
    POST: Triggers evidence-driven optimization evaluation run for the workspace.
    """
    from apps.retrieval.models import RetrievalConfiguration
    from apps.retrieval.optimization import EvidenceDrivenOptimizationService

    workspace_id = request.query_params.get('workspace') or request.data.get('workspace')
    if not workspace_id:
        return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

    workspace = get_object_or_404(Workspace, id=workspace_id)

    if request.method == 'GET':
        configs = RetrievalConfiguration.objects.filter(workspace=workspace).order_by('-is_active', '-version')
        active_cfg = EvidenceDrivenOptimizationService.get_or_create_active_config(workspace)
        return Response({
            'workspace_id': str(workspace.id),
            'active_configuration': active_cfg.to_dict(),
            'configurations': [c.to_dict() for c in configs]
        })

    elif request.method == 'POST':
        # Trigger explicit retrieval optimization evaluation
        custom_cases = request.data.get('custom_cases')
        opt_run = EvidenceDrivenOptimizationService.run_optimization(
            workspace=workspace,
            custom_cases=custom_cases
        )
        return Response({
            'status': opt_run.status,
            'optimization_run_id': str(opt_run.id),
            'decision': opt_run.decision,
            'decision_reason': opt_run.decision_reason,
            'eval_cases_count': opt_run.eval_cases_count,
            'baseline_metrics': opt_run.baseline_metrics,
            'candidate_metrics': opt_run.candidate_metrics,
            'category_breakdown': opt_run.category_breakdown,
            'proposed_config': opt_run.proposed_config.to_dict() if opt_run.proposed_config else None
        })


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def promote_configuration_view(request):
    """Promotes a proposed configuration to active production status with rollback checkpoint."""
    from apps.retrieval.optimization import EvidenceDrivenOptimizationService

    run_id = request.data.get('optimization_run_id')
    if not run_id:
        return Response({'error': 'optimization_run_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user if request.user.is_authenticated else None
    try:
        promoted_cfg = EvidenceDrivenOptimizationService.promote_configuration(run_id, user=user)
        return Response({
            'status': 'promoted',
            'promoted_configuration': promoted_cfg.to_dict(),
            'message': f"Successfully promoted configuration '{promoted_cfg.name}' v{promoted_cfg.version} to active production."
        })
    except Exception as e:
        logger.error(f"Promotion failed for run {run_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def rollback_configuration_view(request):
    """Rolls back the active retrieval configuration to the previous known-good state."""
    from apps.retrieval.optimization import EvidenceDrivenOptimizationService

    workspace_id = request.data.get('workspace')
    target_config_id = request.data.get('target_config_id')
    if not workspace_id:
        return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

    workspace = get_object_or_404(Workspace, id=workspace_id)
    user = request.user if request.user.is_authenticated else None

    try:
        restored_cfg = EvidenceDrivenOptimizationService.rollback_configuration(
            workspace=workspace,
            target_config_id=target_config_id,
            user=user
        )
        return Response({
            'status': 'rolled_back',
            'active_configuration': restored_cfg.to_dict(),
            'message': f"Successfully rolled back active configuration to v{restored_cfg.version} ('{restored_cfg.name}')."
        })
    except Exception as e:
        logger.error(f"Rollback failed for workspace {workspace_id}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def optimization_runs_view(request):
    """Lists retrieval optimization audit runs with baseline vs candidate metrics."""
    from apps.retrieval.models import RetrievalOptimizationRun

    workspace_id = request.query_params.get('workspace')
    if not workspace_id:
        return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

    runs = RetrievalOptimizationRun.objects.filter(workspace_id=workspace_id).select_related(
        'baseline_config', 'proposed_config', 'rollback_config'
    ).order_by('-created_at')[:20]

    output = []
    for r in runs:
        output.append({
            'id': str(r.id),
            'status': r.status,
            'decision': r.decision,
            'decision_reason': r.decision_reason,
            'eval_cases_count': r.eval_cases_count,
            'eval_dataset_version': r.eval_dataset_version,
            'is_promoted': r.is_promoted,
            'baseline_metrics': r.baseline_metrics,
            'candidate_metrics': r.candidate_metrics,
            'category_breakdown': r.category_breakdown,
            'baseline_config': r.baseline_config.to_dict() if r.baseline_config else None,
            'proposed_config': r.proposed_config.to_dict() if r.proposed_config else None,
            'created_at': r.created_at.isoformat(),
        })

    return Response({'runs': output})



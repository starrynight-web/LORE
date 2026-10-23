import time
import json
import urllib.request
from django.conf import settings
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from apps.workspaces.models import Workspace
from apps.decisions.models import DecisionRecord
from .services import HybridRetrievalService
from apps.decisions.engine import AnswerStateMachine
from apps.governance.layers import EnterpriseGovernanceEngine

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
        limit=10
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


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
from apps.audit.models import AuditEvent
from .services import HybridRetrievalService
from apps.decisions.engine import AnswerStateMachine

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def search_view(request):
    """Hybrid lexical + vector search across authorized workspace chunks."""
    workspace_id = request.data.get('workspace')
    query = request.data.get('query', '')
    collection_id = request.data.get('collection')
    limit = int(request.data.get('limit', 8))

    if not workspace_id:
        return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not query.strip():
        return Response({'results': []})

    workspace = get_object_or_404(Workspace, id=workspace_id, memberships__user=request.user)

    retrieval_service = HybridRetrievalService()
    results = retrieval_service.search(
        query=query,
        workspace_id=str(workspace.id),
        organization_id=str(workspace.organization.id),
        collection_id=collection_id,
        limit=limit
    )

    return Response({
        'query': query,
        'workspace': str(workspace.id),
        'results_count': len(results),
        'results': results
    })

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
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

    workspace = get_object_or_404(Workspace, id=workspace_id, memberships__user=request.user)

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

    # 1. Retrieve Candidate Chunks
    retrieval_service = HybridRetrievalService()
    candidate_chunks = retrieval_service.search(
        query=query,
        workspace_id=str(workspace.id),
        organization_id=str(workspace.organization.id),
        collection_id=collection_id,
        limit=10
    )

    # 2. Evaluate via 9-State Governance Machine with Anti-Hallucination & Groq gpt-oss-120B
    envelope = AnswerStateMachine.evaluate(
        query=query,
        retrieved_chunks=candidate_chunks,
        workspace_id=str(workspace.id),
        user=request.user,
        groq_api_key=groq_api_key,
        llm_model=llm_model
    )

    # 3. Record Metered Query Usage
    QuotaEnforcementService.record_query(workspace.organization, workspace, envelope.get('token_count', 0))

    # 4. Persist Decision Record
    decision = DecisionRecord.objects.create(
        trace_id=envelope['trace_id'],
        organization=workspace.organization,
        workspace=workspace,
        user=request.user,
        query=query,
        decision_type=envelope['decision_type'],
        state=envelope['state'],
        directive=envelope['directive'],
        answer_text=envelope.get('answer', ''),
        evidence_found=envelope.get('evidence_found', []),
        evidence_missing=envelope.get('evidence_missing', []),
        conflicts_resolved=envelope.get('conflicts_resolved', []),
        citations=envelope.get('citations', []),
        token_count=envelope.get('token_count', 0)
    )

    # 5. Log Audit Event
    AuditEvent.objects.create(
        organization=workspace.organization,
        workspace=workspace,
        user=request.user,
        event_type='retrieval_query',
        target_type='decision',
        target_id=str(decision.id),
        details={
            'query': query,
            'state': envelope['state'],
            'directive': envelope['directive'],
            'citations_count': len(envelope.get('citations', []))
        }
    )

    return Response(envelope)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
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


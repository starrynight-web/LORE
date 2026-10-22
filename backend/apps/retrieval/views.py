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

    # 1. Retrieve Candidate Chunks
    retrieval_service = HybridRetrievalService()
    candidate_chunks = retrieval_service.search(
        query=query,
        workspace_id=str(workspace.id),
        organization_id=str(workspace.organization.id),
        collection_id=collection_id,
        limit=10
    )

    # 2. Evaluate via 9-State Governance Machine
    envelope = AnswerStateMachine.evaluate(
        query=query,
        retrieved_chunks=candidate_chunks,
        workspace_id=str(workspace.id),
        user=request.user
    )

    # 3. Persist Decision Record
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

    # 4. Log Audit Event
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

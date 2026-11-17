"""
LORE Enterprise - Knowledge Grid & GraphRAG API Views (docs/enterprise/fix/knowledge.md §2 & prompt §1.5)
Provides workspace-scoped graph inspection:
- RAPTOR DomainSummary community nodes (<= 800 tokens)
- CanonicalEntity ontology clusters (Vendor, System, Regulation, Rule, etc.)
- KnowledgeRelationship typed semantic edges
"""

import logging
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.knowledge.models import (
    CanonicalEntity,
    DomainSummary,
    KnowledgeRelationship,
    KnowledgeItem,
)
from apps.workspaces.models import Workspace

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def graph_overview_view(request):
    """
    GET /api/v1/knowledge/graph-overview/?workspace_id=<uuid>
    Returns:
    - domain_summaries: RAPTOR community summaries with <= 800 token verified badges
    - canonical_entities: clusters categorized by entity_type (Vendor, System, Regulation, Component, etc.)
    - edge_metrics: active GOVERNED_BY, CONFLICTS_WITH, SUPERSEDES, APPLIES_TO, REQUIRES edge counts
    - edges: recent semantic edges
    """
    ws_id = request.query_params.get('workspace_id')
    if not ws_id:
        return Response({'error': 'workspace_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

    ws = Workspace.objects.filter(id=ws_id).first()
    if not ws:
        return Response({'error': 'Workspace not found.'}, status=status.HTTP_404_NOT_FOUND)

    # 1. RAPTOR Domain Summaries (Hierarchical Communities)
    summaries_qs = DomainSummary.objects.filter(workspace=ws).order_by('-community_level', '-created_at')
    domain_summaries = []
    for s in summaries_qs[:30]:
        domain_summaries.append({
            "id": str(s.id),
            "level": s.community_level,
            "domain_name": s.domain_name,
            "summary_text": s.summary_text,
            "token_count": s.token_count,
            "within_token_budget": s.token_count <= 800,
            "entity_count": len(s.entity_ids or []),
            "rule_count": len(s.rule_ids or []),
            "created_at": s.created_at.isoformat(),
        })

    # If no RAPTOR summaries generated yet, produce baseline community representation
    if not domain_summaries:
        domain_summaries.append({
            "id": f"summary-baseline-{ws.id}",
            "level": 0,
            "domain_name": f"{ws.name} Core Enterprise Knowledge",
            "summary_text": f"Enterprise knowledge base for workspace {ws.name}. Enforces 9-layer fail-closed deterministic governance and authorized ABAC policies.",
            "token_count": 42,
            "within_token_budget": True,
            "entity_count": CanonicalEntity.objects.filter(workspace=ws).count(),
            "rule_count": KnowledgeItem.objects.filter(workspace=ws).count(),
            "created_at": ws.created_at.isoformat() if hasattr(ws, 'created_at') else "",
        })

    # 2. Canonical Entities (Categorized by Ontology Type)
    entities_qs = CanonicalEntity.objects.filter(workspace=ws).order_by('entity_type', 'name')
    canonical_entities = []
    entities_by_type = {}
    for ent in entities_qs[:150]:
        e_type = ent.entity_type
        entities_by_type[e_type] = entities_by_type.get(e_type, 0) + 1
        canonical_entities.append({
            "id": str(ent.id),
            "name": ent.name,
            "canonical_name": ent.canonical_name,
            "entity_type": ent.entity_type,
            "aliases": ent.aliases,
            "description": ent.description,
            "properties": ent.properties,
        })

    # 3. Knowledge Relationships & Edge Distribution
    edges_qs = KnowledgeRelationship.objects.filter(workspace=ws)
    total_edges = edges_qs.count()
    edge_types = {}
    for r_type in [
        "APPLIES_TO", "GOVERNED_BY", "CONFLICTS_WITH",
        "SUPERSEDES", "DEPENDS_ON", "REQUIRES", "OVERRIDES", "DERIVED_FROM"
    ]:
        edge_types[r_type] = edges_qs.filter(relationship_type=r_type).count()

    recent_edges = []
    for rel in edges_qs.filter(approval_status="approved").order_by('-created_at')[:50]:
        source_id = (
            str(rel.source_canonical_entity_id) if rel.source_canonical_entity_id
            else str(rel.source_item_id) if rel.source_item_id
            else str(rel.source_document_id) if rel.source_document_id
            else str(rel.source_chunk_id) if rel.source_chunk_id
            else ""
        )
        target_id = (
            str(rel.target_canonical_entity_id) if rel.target_canonical_entity_id
            else str(rel.target_item_id) if rel.target_item_id
            else str(rel.target_document_id) if rel.target_document_id
            else str(rel.target_chunk_id) if rel.target_chunk_id
            else ""
        )
        recent_edges.append({
            "id": str(rel.id),
            "relationship_type": rel.relationship_type,
            "source_id": source_id,
            "target_id": target_id,
            "confidence": rel.confidence,
            "provenance": rel.provenance,
            "approval_status": rel.approval_status,
        })

    return Response({
        "status": "SUCCESS",
        "workspace_id": str(ws.id),
        "workspace_name": ws.name,
        "domain_summaries": domain_summaries,
        "domain_summaries_count": len(domain_summaries),
        "canonical_entities": canonical_entities,
        "canonical_entities_count": len(canonical_entities),
        "entities_by_type": entities_by_type,
        "edge_metrics": edge_types,
        "total_edges": total_edges,
        "recent_edges": recent_edges,
    })

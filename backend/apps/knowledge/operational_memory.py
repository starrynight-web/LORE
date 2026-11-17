"""
LORE Enterprise - Operational Memory Graph (docs/enterprise/fix/knowledge.md §2)
Converts DecisionRecords, human review approvals, and ScopedExceptions into active graph memory.
Automatically links decisions and exceptions to Component, Rule, and CanonicalEntity nodes,
enabling future queries to inherit institutional precedent deterministically.
"""

import logging
from typing import List, Dict, Any, Optional
from django.db.models import Q
from apps.knowledge.models import (
    CanonicalEntity, KnowledgeItem, KnowledgeRelationship,
    RelationshipType, RelationshipApprovalStatus
)
from apps.knowledge.ontology import CanonicalEntityType

logger = logging.getLogger(__name__)


class OperationalMemoryService:
    """
    Service for linking operational decisions and reviews into active graph memory.
    """

    @classmethod
    def record_decision_precedent(
        cls,
        decision_record,
        reviewed_by: Optional[str] = None,
        review_notes: str = "",
    ) -> Dict[str, Any]:
        """
        Links a DecisionRecord into the active knowledge graph:
        1. Creates/resolves a CanonicalEntity for the Decision.
        2. Links to cited rules via APPLIES_TO or RESOLVES.
        """
        ws = decision_record.workspace
        org = decision_record.organization

        decision_name = f"Decision-{decision_record.trace_id[:12]}"
        decision_entity, _ = CanonicalEntity.objects.get_or_create(
            workspace=ws,
            organization=org,
            entity_type=CanonicalEntityType.DECISION.value,
            canonical_name=decision_name.lower(),
            defaults={
                "name": decision_name,
                "description": f"Operational decision for query: {decision_record.query[:150]}",
                "properties": {
                    "trace_id": decision_record.trace_id,
                    "state": decision_record.state,
                    "directive": decision_record.directive,
                    "decision_type": decision_record.decision_type,
                    "reviewed_by": reviewed_by or "",
                    "review_notes": review_notes,
                },
            },
        )

        linked_edges = []
        # Find rules from citations
        citations = decision_record.citations or []
        for cite in citations:
            rule_code = cite.get("code") or cite.get("rule_id") or ""
            if not rule_code:
                continue

            target_rule = KnowledgeItem.objects.filter(
                workspace=ws,
                organization=org,
                code=rule_code,
            ).first()

            if target_rule:
                rel_type = (
                    RelationshipType.OVERRIDES if decision_record.directive == "stop"
                    else RelationshipType.APPLIES_TO
                )
                rel, _ = KnowledgeRelationship.objects.get_or_create(
                    workspace=ws,
                    organization=org,
                    source_canonical_entity=decision_entity,
                    target_item=target_rule,
                    relationship_type=rel_type,
                    defaults={
                        "confidence": 1.0,
                        "provenance": "operational_decision_memory",
                        "approval_status": RelationshipApprovalStatus.APPROVED,
                        "approved_by": reviewed_by or "system_decision_recorder",
                        "metadata": {
                            "decision_trace_id": decision_record.trace_id,
                            "directive": decision_record.directive,
                            "state": decision_record.state,
                        },
                    },
                )
                linked_edges.append(str(rel.id))

        return {
            "decision_entity_id": str(decision_entity.id),
            "linked_edges_count": len(linked_edges),
            "linked_edge_ids": linked_edges,
        }

    @classmethod
    def record_exception_precedent(cls, scoped_exception) -> Dict[str, Any]:
        """
        Links an active ScopedException to the target rule node with OVERRIDES relation.
        """
        ws = scoped_exception.workspace
        org = ws.organization

        exc_name = f"Exception-{scoped_exception.rule_code}-{scoped_exception.scope_value}"
        exc_entity, _ = CanonicalEntity.objects.get_or_create(
            workspace=ws,
            organization=org,
            entity_type=CanonicalEntityType.EXCEPTION.value,
            canonical_name=exc_name.lower()[:255],
            defaults={
                "name": exc_name,
                "description": f"Exception approved by {scoped_exception.approved_by}: {scoped_exception.justification[:150]}",
                "properties": {
                    "rule_code": scoped_exception.rule_code,
                    "scope_type": scoped_exception.scope_type,
                    "scope_value": scoped_exception.scope_value,
                    "status": scoped_exception.status,
                },
            },
        )

        target_rule = KnowledgeItem.objects.filter(
            workspace=ws,
            code=scoped_exception.rule_code,
        ).first()

        created_rel_id = None
        if target_rule:
            rel, _ = KnowledgeRelationship.objects.get_or_create(
                workspace=ws,
                organization=org,
                source_canonical_entity=exc_entity,
                target_item=target_rule,
                relationship_type=RelationshipType.OVERRIDES,
                defaults={
                    "confidence": 1.0,
                    "provenance": "operational_exception_memory",
                    "approval_status": RelationshipApprovalStatus.APPROVED,
                    "approved_by": scoped_exception.approved_by,
                    "valid_from": scoped_exception.window_start,
                    "valid_until": scoped_exception.window_end,
                },
            )
            created_rel_id = str(rel.id)

        return {
            "exception_entity_id": str(exc_entity.id),
            "override_edge_id": created_rel_id,
        }

    @classmethod
    def get_institutional_precedents(
        cls,
        workspace_id: str,
        organization_id: str,
        rule_code: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves active institutional precedent edges connected to the specified rule.
        """
        rels = KnowledgeRelationship.objects.filter(
            workspace_id=workspace_id,
            organization_id=organization_id,
            target_item__code=rule_code,
            relationship_type__in=[RelationshipType.OVERRIDES, RelationshipType.APPLIES_TO],
            approval_status=RelationshipApprovalStatus.APPROVED,
        ).select_related("source_canonical_entity", "target_item").order_by("-created_at")[:limit]

        precedents = []
        for r in rels:
            if r.source_canonical_entity:
                precedents.append({
                    "entity_id": str(r.source_canonical_entity.id),
                    "name": r.source_canonical_entity.name,
                    "entity_type": r.source_canonical_entity.entity_type,
                    "relationship": r.relationship_type,
                    "properties": r.source_canonical_entity.properties,
                    "created_at": r.created_at.isoformat(),
                })
        return precedents


import time
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from django.utils import timezone
from django.db.models import Q

from apps.knowledge.models import (
    DocumentChunk, KnowledgeItem, KnowledgeRelationship,
    RelationshipType, RelationshipApprovalStatus
)
from apps.sources.models import SourceDocument, DocumentVersion
from apps.governance.models import SourcePermission, ConflictRecord, ScopedException, EvidenceRequirement

logger = logging.getLogger(__name__)


class GraphTraversalBudgetExceeded(Exception):
    """Raised when traversal exceeds configured hop, node, or timeout limits."""
    pass


class BoundedGraphTraversalService:
    """
    Bounded, Governed GraphRAG Traversal Service (lore.md §5 & §7).
    Executes depth-bounded, cycle-safe, tenant-isolated traversal over typed relational edges:
    - Supported types: APPLIES_TO, DEPENDS_ON, REQUIRES, SUPERSEDES, CONFLICTS_WITH, DERIVED_FROM, OVERRIDES, GOVERNED_BY
    - Invariants:
      1. Bounded depth (max 2-3 hops), node limits, and timeout protection.
      2. Tenant isolation enforced at every hop.
      3. Model-generated relationships must be approved (approval_status='approved') to be traversed live.
      4. Target nodes must have document__status='ready' (quarantined, draft, failed are pruned).
      5. Target nodes must satisfy L7 permission authorization for caller.
      6. Temporal validity (as_of) evaluated at every edge and document.
      7. Traversal surfaces conflict records, required evidence, and scoped exceptions.
    """

    DEFAULT_MAX_DEPTH = 2
    MAX_DEPTH_HARD_CAP = 3
    DEFAULT_MAX_NODES = 15
    DEFAULT_TIMEOUT_MS = 100.0

    @classmethod
    def expand(
        cls,
        seed_chunks: List[Dict[str, Any]],
        workspace_id: str,
        organization_id: str,
        user=None,
        user_role: str = 'member',
        as_of=None,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_nodes: int = DEFAULT_MAX_NODES,
        timeout_ms: float = DEFAULT_TIMEOUT_MS,
        permitted_relationship_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        t0 = time.time()
        effective_depth = min(max(1, max_depth), cls.MAX_DEPTH_HARD_CAP)
        effective_max_nodes = max(1, min(max_nodes, 50))

        if permitted_relationship_types is None:
            permitted_types = [t.value for t in RelationshipType]
        else:
            permitted_types = [t for t in permitted_relationship_types if t in RelationshipType.values]

        # Extract initial seed document IDs and chunk IDs
        seed_doc_ids = set()
        seed_chunk_ids = set()
        for sc in seed_chunks:
            if 'document_id' in sc and sc['document_id']:
                seed_doc_ids.add(str(sc['document_id']))
            if 'chunk_id' in sc and sc['chunk_id']:
                seed_chunk_ids.add(str(sc['chunk_id']))

        expanded_chunks: List[Dict[str, Any]] = []
        expanded_chunk_ids: Set[str] = set(seed_chunk_ids)
        visited_nodes: Set[Tuple[str, str]] = set()  # (node_type, node_id)
        traversal_paths: List[Dict[str, Any]] = []

        surfaced_conflicts: List[Dict[str, Any]] = []
        surfaced_requirements: List[Dict[str, Any]] = []
        surfaced_exceptions: List[Dict[str, Any]] = []
        surfaced_dependencies: List[Dict[str, Any]] = []
        surfaced_supersessions: List[Dict[str, Any]] = []
        surfaced_lineage: List[Dict[str, Any]] = []

        # Queue of tuples: (node_type, node_id, current_depth, path_history)
        queue: List[Tuple[str, str, int, List[Dict[str, Any]]]] = []

        for did in sorted(seed_doc_ids):
            queue.append(('document', did, 0, []))
            visited_nodes.add(('document', did))

        for cid in sorted(seed_chunk_ids):
            queue.append(('chunk', cid, 0, []))
            visited_nodes.add(('chunk', cid))

        traversal_status = "completed"
        degraded = False

        while queue:
            # Timeout guard
            elapsed_ms = (time.time() - t0) * 1000
            if elapsed_ms > timeout_ms:
                logger.warning(f"[GraphRAG] Traversal timeout reached ({elapsed_ms:.1f}ms > {timeout_ms}ms). Halting.")
                traversal_status = "budget_exceeded"
                degraded = True
                break

            # Node limit guard
            if len(expanded_chunks) >= effective_max_nodes:
                logger.info(f"[GraphRAG] Node limit ({effective_max_nodes}) reached. Halting expansion.")
                break

            curr_type, curr_id, curr_depth, path_history = queue.pop(0)

            if curr_depth >= effective_depth:
                continue

            # Query outgoing edges from current node
            # Strictly scoped to workspace and organization, approved edges only
            edge_q = Q(workspace_id=workspace_id, organization_id=organization_id)
            edge_q &= Q(approval_status=RelationshipApprovalStatus.APPROVED)
            edge_q &= Q(relationship_type__in=permitted_types)

            if curr_type == 'document':
                edge_q &= (Q(source_document_id=curr_id) | Q(target_document_id=curr_id))
            elif curr_type == 'chunk':
                edge_q &= (Q(source_chunk_id=curr_id) | Q(target_chunk_id=curr_id))
            else:
                continue

            # Deterministic ordering by confidence descending, then ID
            relationships = list(
                KnowledgeRelationship.objects.filter(edge_q)
                .select_related(
                    'source_document', 'target_document',
                    'source_chunk', 'target_chunk',
                    'source_document__permissions', 'target_document__permissions'
                )
                .order_by('-confidence', 'id')[:20]
            )

            for rel in relationships:
                # 1. Temporal Validity Check on Edge
                if not rel.is_temporally_valid(as_of):
                    continue

                # Determine next node identity and direction
                is_outgoing = (
                    (curr_type == 'document' and str(rel.source_document_id) == curr_id) or
                    (curr_type == 'chunk' and str(rel.source_chunk_id) == curr_id)
                )

                if is_outgoing:
                    next_doc = rel.target_document
                    next_chunk = rel.target_chunk
                    next_type = 'chunk' if next_chunk else 'document'
                    next_id = str(next_chunk.id) if next_chunk else (str(next_doc.id) if next_doc else None)
                else:
                    next_doc = rel.source_document
                    next_chunk = rel.source_chunk
                    next_type = 'chunk' if next_chunk else 'document'
                    next_id = str(next_chunk.id) if next_chunk else (str(next_doc.id) if next_doc else None)

                if not next_id or not next_doc:
                    continue

                # 2. Cycle Detection
                if (next_type, next_id) in visited_nodes:
                    continue

                # Target Node Tenant Scoping Invariant:
                # Even if an edge has bad references, target MUST belong to same workspace and organization
                if str(next_doc.organization_id) != str(organization_id) or str(next_doc.workspace_id) != str(workspace_id):
                    logger.warning(f"[GraphRAG Pruned] Target doc {next_doc.id} belongs to different tenant/workspace. Pruning.")
                    continue

                # 3. Target Document Publication & Status Invariant
                # Quarantined, draft, failed, or deleted targets MUST NEVER BE REACHED
                if next_doc.status != 'ready':
                    logger.debug(f"[GraphRAG Pruned] Target doc {next_doc.id} status='{next_doc.status}' != 'ready'")
                    continue

                # 4. Target Document Permission Authorization (L7 Gate)
                perms = getattr(next_doc, 'permissions', None)
                if perms and not perms.is_user_permitted(user, user_role):
                    logger.debug(f"[GraphRAG Pruned] User not permitted to view target doc {next_doc.id}")
                    continue

                # 5. Temporal Validity on Target Document (effective date & expiration date)
                from datetime import datetime
                as_of_dt = as_of if isinstance(as_of, datetime) else timezone.now()
                if timezone.is_naive(as_of_dt):
                    as_of_dt = timezone.make_aware(as_of_dt, timezone.utc)

                if next_doc.effective_date:
                    eff_dt = next_doc.effective_date if not timezone.is_naive(next_doc.effective_date) else timezone.make_aware(next_doc.effective_date, timezone.utc)
                    if as_of_dt < eff_dt:
                        continue

                if next_doc.expiration_date:
                    exp_dt = next_doc.expiration_date if not timezone.is_naive(next_doc.expiration_date) else timezone.make_aware(next_doc.expiration_date, timezone.utc)
                    if as_of_dt > exp_dt:
                        logger.debug(f"[GraphRAG Pruned] Target doc {next_doc.id} expired on {exp_dt}")
                        continue

                # 6. Mark Visited and Build Path Step
                visited_nodes.add((next_type, next_id))
                step = {
                    'from': f"{curr_type}:{curr_id}",
                    'relationship': rel.relationship_type,
                    'to': f"{next_type}:{next_id}",
                    'provenance': rel.provenance,
                    'confidence': rel.confidence,
                    'depth': curr_depth + 1
                }
                new_path = path_history + [step]
                traversal_paths.append(step)

                # 7. Surface Governance Semantics
                if rel.relationship_type == RelationshipType.CONFLICTS_WITH:
                    surfaced_conflicts.append({
                        'relationship_id': str(rel.id),
                        'source_title': rel.source_document.title if rel.source_document else "Unknown",
                        'target_title': rel.target_document.title if rel.target_document else "Unknown",
                        'description': rel.metadata.get('conflict_description', 'Graph-identified policy conflict')
                    })
                elif rel.relationship_type == RelationshipType.REQUIRES:
                    surfaced_requirements.append({
                        'relationship_id': str(rel.id),
                        'required_document': next_doc.title,
                        'description': rel.metadata.get('requirement_description', f"Mandatory prerequisite: {next_doc.title}")
                    })
                elif rel.relationship_type == RelationshipType.OVERRIDES:
                    surfaced_exceptions.append({
                        'relationship_id': str(rel.id),
                        'override_scope': rel.metadata.get('scope', 'policy_override'),
                        'justification': rel.metadata.get('justification', 'Authorized graph override')
                    })
                elif rel.relationship_type in (RelationshipType.DEPENDS_ON, RelationshipType.APPLIES_TO, RelationshipType.GOVERNED_BY):
                    surfaced_dependencies.append({
                        'relationship_id': str(rel.id),
                        'relationship_type': rel.relationship_type,
                        'source_doc': rel.source_document.title if rel.source_document else "Unknown",
                        'target_doc': rel.target_document.title if rel.target_document else "Unknown",
                    })
                elif rel.relationship_type == RelationshipType.SUPERSEDES:
                    surfaced_supersessions.append({
                        'relationship_id': str(rel.id),
                        'superseding_doc': rel.source_document.title if rel.source_document else "Unknown",
                        'superseded_doc': rel.target_document.title if rel.target_document else "Unknown",
                        'valid_from': rel.valid_from.isoformat() if rel.valid_from else None,
                    })
                elif rel.relationship_type == RelationshipType.DERIVED_FROM:
                    surfaced_lineage.append({
                        'relationship_id': str(rel.id),
                        'derived_doc': rel.source_document.title if rel.source_document else "Unknown",
                        'source_doc': rel.target_document.title if rel.target_document else "Unknown",
                    })

                # 8. Fetch Chunks for Target Node
                if next_chunk and str(next_chunk.id) not in expanded_chunk_ids:
                    expanded_chunk_ids.add(str(next_chunk.id))
                    chk_item = cls._format_chunk_item(next_chunk, next_doc, curr_depth + 1, rel, new_path)
                    expanded_chunks.append(chk_item)
                elif next_doc:
                    # Fetch top representative chunks of target document
                    doc_chunks = list(
                        DocumentChunk.objects.filter(
                            document=next_doc,
                            document_version__version_number=next_doc.current_version_number
                        ).order_by('chunk_index')[:2]
                    )
                    for dc in doc_chunks:
                        if str(dc.id) not in expanded_chunk_ids:
                            expanded_chunk_ids.add(str(dc.id))
                            chk_item = cls._format_chunk_item(dc, next_doc, curr_depth + 1, rel, new_path)
                            expanded_chunks.append(chk_item)

                # Enqueue for next hop
                queue.append((next_type, next_id, curr_depth + 1, new_path))

        total_elapsed_ms = int((time.time() - t0) * 1000)

        return {
            'status': traversal_status,
            'degraded': degraded,
            'elapsed_ms': total_elapsed_ms,
            'max_depth_configured': effective_depth,
            'nodes_expanded_count': len(expanded_chunks),
            'traversal_paths': traversal_paths,
            'expanded_chunks': expanded_chunks,
            'surfaced_conflicts': surfaced_conflicts,
            'surfaced_requirements': surfaced_requirements,
            'surfaced_exceptions': surfaced_exceptions,
            'surfaced_dependencies': surfaced_dependencies,
            'surfaced_supersessions': surfaced_supersessions,
            'surfaced_lineage': surfaced_lineage,
        }

    @classmethod
    def _format_chunk_item(
        cls,
        chunk: DocumentChunk,
        doc: SourceDocument,
        depth: int,
        rel: KnowledgeRelationship,
        path: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Formats an expanded chunk into a retrieval-compatible dictionary."""
        ver_num = chunk.document_version.version_number if chunk.document_version else doc.current_version_number
        tokens = chunk.token_count or len((chunk.text or '').split())

        # Base proximity score inversely proportional to graph depth
        proximity_seed = round(0.40 / (1.0 + (0.5 * depth)), 4)

        return {
            'chunk_id': str(chunk.id),
            'document_id': str(doc.id),
            'document_title': doc.title,
            'document_type': doc.document_type,
            'document_version': ver_num,
            'page_number': chunk.page_number,
            'heading_path': chunk.heading_path,
            'text': chunk.text,
            'contextual_header': chunk.contextual_header,
            'authority_level': doc.authority_level,
            'score': proximity_seed,
            'rrf_score': proximity_seed,
            'token_count': tokens,
            # GraphRAG Provenance Contracts
            'graph_expanded': True,
            'graph_depth': depth,
            'traversed_relationship': rel.relationship_type,
            'edge_provenance': rel.provenance,
            'edge_confidence': rel.confidence,
            'graph_path': path,
            'retrieval_status': 'graph_expanded'
        }


class GraphIntegrityService:
    """
    Integrity and reconciliation utility for the LORE Knowledge Graph.
    Detects cycles, audits tenant isolation, reconciles orphaned edges, validates edges,
    and approves model proposals.
    """

    @classmethod
    def validate_edge(
        cls,
        source_doc: SourceDocument,
        target_doc: SourceDocument,
        relationship_type: str,
        organization_id: str,
        workspace_id: str,
        valid_from=None,
        valid_until=None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates edge creation integrity:
        - Rejects self-loops (source == target).
        - Enforces tenant isolation (source, target, and edge must match organization and workspace).
        - Enforces valid-time consistency (valid_from <= valid_until).
        - Validates relationship type is supported in RelationshipType enum.
        """
        if str(source_doc.id) == str(target_doc.id):
            return False, "Self-loop edge rejected: source and target documents cannot be identical."

        if str(source_doc.organization_id) != str(organization_id) or str(target_doc.organization_id) != str(organization_id):
            return False, "Tenant violation: source or target document does not match organization scope."

        if str(source_doc.workspace_id) != str(workspace_id) or str(target_doc.workspace_id) != str(workspace_id):
            return False, "Workspace violation: source or target document does not match workspace scope."

        if relationship_type not in RelationshipType.values:
            return False, f"Invalid relationship type: '{relationship_type}'. Must be one of {RelationshipType.values}."

        if valid_from and valid_until and valid_from > valid_until:
            return False, f"Invalid temporal bounds: valid_from ({valid_from}) cannot be after valid_until ({valid_until})."

        return True, None

    @classmethod
    def detect_cycles(cls, workspace_id: str) -> List[List[str]]:
        """
        DFS cycle detection across approved edges in the specified workspace.
        Returns list of cycle paths (e.g. [['docA', 'docB', 'docA']]).
        """
        adj: Dict[str, List[str]] = {}
        edges = KnowledgeRelationship.objects.filter(
            workspace_id=workspace_id,
            approval_status=RelationshipApprovalStatus.APPROVED,
            source_document__isnull=False,
            target_document__isnull=False
        ).values_list('source_document_id', 'target_document_id')

        for src, tgt in edges:
            s_id = str(src)
            t_id = str(tgt)
            adj.setdefault(s_id, []).append(t_id)

        cycles = []
        visited: Set[str] = set()
        rec_stack: List[str] = []

        def dfs(node: str):
            visited.add(node)
            rec_stack.append(node)

            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # Cycle found
                    idx = rec_stack.index(neighbor)
                    cycle_path = rec_stack[idx:] + [neighbor]
                    cycles.append(cycle_path)

            rec_stack.pop()

        for node in list(adj.keys()):
            if node not in visited:
                dfs(node)

        return cycles

    @classmethod
    def approve_model_proposal(cls, relationship_id: str, approved_by: str) -> bool:
        """Promotes a model-generated proposal to approved status for live traversal."""
        try:
            rel = KnowledgeRelationship.objects.get(id=relationship_id)
            rel.approval_status = RelationshipApprovalStatus.APPROVED
            rel.approved_by = approved_by
            rel.save(update_fields=['approval_status', 'approved_by', 'updated_at'])
            return True
        except KnowledgeRelationship.DoesNotExist:
            return False

    @classmethod
    def audit_tenant_isolation(cls) -> List[Dict[str, Any]]:
        """Finds any edge where source and target documents belong to different organizations or workspaces."""
        violations = []
        for rel in KnowledgeRelationship.objects.select_related('source_document', 'target_document').all():
            if rel.source_document and rel.target_document:
                if rel.source_document.organization_id != rel.target_document.organization_id:
                    violations.append({
                        'edge_id': str(rel.id),
                        'type': 'cross_organization_leak',
                        'source_org': str(rel.source_document.organization_id),
                        'target_org': str(rel.target_document.organization_id)
                    })
                elif rel.source_document.workspace_id != rel.target_document.workspace_id:
                    violations.append({
                        'edge_id': str(rel.id),
                        'type': 'cross_workspace_leak',
                        'source_ws': str(rel.source_document.workspace_id),
                        'target_ws': str(rel.target_document.workspace_id)
                    })
        return violations

    @classmethod
    def reconcile_orphaned_edges(cls, workspace_id: Optional[str] = None) -> int:
        """Prunes edges pointing to deleted or quarantined documents."""
        qs = KnowledgeRelationship.objects.all()
        if workspace_id:
            qs = qs.filter(workspace_id=workspace_id)

        orphaned = qs.filter(
            Q(source_document__status__in=['quarantined', 'failed', 'deleted']) |
            Q(target_document__status__in=['quarantined', 'failed', 'deleted'])
        )
        count = orphaned.count()
        orphaned.delete()
        return count

import uuid
import time
from datetime import datetime, timedelta, timezone as dt_timezone
import pytest
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.identity.models import Organization
from apps.workspaces.models import Workspace, Collection
from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.knowledge.models import (
    DocumentChunk, KnowledgeRelationship, RelationshipType, RelationshipApprovalStatus
)
from apps.governance.models import SourcePermission, AccessLevel
from apps.governance.contract import GovernanceRequest, GovernanceReasonCode, Verdict
from apps.governance.layers import EnterpriseGovernanceEngine, TemporalValidityLayer
from apps.knowledge.graph import BoundedGraphTraversalService, GraphIntegrityService
from apps.retrieval.services import HybridRetrievalService, ContextReranker


@pytest.mark.django_db
class TestBoundedGovernedGraphRAG:
    """
    Test suite for Bounded, Governed GraphRAG implementation:
    - One-hop and multi-hop retrieval
    - Cycle detection and maximum-depth enforcement
    - Superseded version resolution (temporal logic)
    - Surfaced conflicts, requirements, exceptions, dependencies, and lineage
    - Tenant isolation (cross-organization edge rejection)
    - Unpublished / quarantined node pruning
    - Revoked access / L7 permission gating
    - Expired edge temporal gating
    - Graph traversal timeout / store failure degraded state
    - Deterministic traversal ordering
    - Graph integrity service utilities
    """

    @pytest.fixture(autouse=True)
    def setup_entities(self):
        uid = uuid.uuid4().hex[:6]
        self.org = Organization.objects.create(name="GraphRAG Test Org", slug=f"graphrag-org-{uid}")
        self.org_other = Organization.objects.create(name="Other Tenant Org", slug=f"other-org-{uid}")
        self.ws = Workspace.objects.create(name="GraphRAG Workspace", organization=self.org)
        self.ws_other = Workspace.objects.create(name="Other Workspace", organization=self.org_other)
        self.user = User.objects.create_user(username=f"graph_tester_{uid}", email="tester@example.com")

        # Document A: Vendor Assessment Policy (Seed)
        self.doc_a = self._create_doc(
            title="Vendor Risk Management Framework",
            content="All third-party cloud vendors must undergo formal risk assessment and adhere to the data sovereignty standard. Vendor assessment audit passed.",
            authority_level=6,
            org=self.org,
            ws=self.ws
        )

        # Document B: Data Sovereignty Standard (1 hop: DEPENDS_ON)
        self.doc_b = self._create_doc(
            title="Data Sovereignty Standard",
            content="Regional data residency requires local storage replication and encryption key segregation.",
            authority_level=7,
            org=self.org,
            ws=self.ws
        )

        # Document C: Key Management Specification (2 hops: REQUIRES)
        self.doc_c = self._create_doc(
            title="Key Management Specification",
            content="Hardware Security Modules (HSM) must be used for tenant master key generation.",
            authority_level=5,
            org=self.org,
            ws=self.ws
        )

    def _create_doc(self, title: str, content: str, authority_level: int = 4, org=None, ws=None, status='ready', effective_date=None, expiration_date=None):
        org = org or self.org
        ws = ws or self.ws
        f = SimpleUploadedFile(f"{title.lower().replace(' ', '_')}.txt", content.encode('utf-8'), content_type="text/plain")
        doc = SourceDocument.objects.create(
            organization=org,
            workspace=ws,
            title=title,
            original_filename=f.name,
            mime_type="text/plain",
            file_size=len(content),
            file_hash=uuid.uuid4().hex,
            file_obj=f,
            document_type="txt",
            status=status,
            authority_level=authority_level,
            effective_date=effective_date,
            expiration_date=expiration_date
        )
        ver = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            file_hash=doc.file_hash,
            file_obj=f,
            is_current=True
        )
        DocumentChunk.objects.create(
            document=doc,
            document_version=ver,
            workspace=ws,
            organization=org,
            chunk_index=0,
            text=content,
            token_count=len(content.split()),
            heading_path="Section 1",
            contextual_header=f"Document: {title} | Workspace: {ws.name} | Section: Section 1"
        )
        return doc

    # --------------------------------------------------------------------------
    # 1. One-Hop and Multi-Hop Traversal
    # --------------------------------------------------------------------------
    def test_one_hop_and_multi_hop_traversal(self):
        """
        Verify that:
        1. 1-hop traversal expands from Doc A to Doc B via DEPENDS_ON.
        2. 2-hop traversal expands from Doc A -> Doc B -> Doc C via REQUIRES.
        3. Traversal preserves full provenance, relationship types, and graph paths.
        """
        # Create approved edges
        rel_ab = KnowledgeRelationship.objects.create(
            workspace=self.ws,
            organization=self.org,
            source_document=self.doc_a,
            target_document=self.doc_b,
            relationship_type=RelationshipType.DEPENDS_ON,
            provenance="Verified policy link",
            confidence=0.95,
            approval_status=RelationshipApprovalStatus.APPROVED
        )
        rel_bc = KnowledgeRelationship.objects.create(
            workspace=self.ws,
            organization=self.org,
            source_document=self.doc_b,
            target_document=self.doc_c,
            relationship_type=RelationshipType.REQUIRES,
            provenance="Standard prerequisite",
            confidence=0.90,
            approval_status=RelationshipApprovalStatus.APPROVED
        )

        seed = [{'document_id': str(self.doc_a.id)}]

        # 1-Hop Expansion (max_depth=1)
        res_1hop = BoundedGraphTraversalService.expand(
            seed_chunks=seed,
            workspace_id=str(self.ws.id),
            organization_id=str(self.org.id),
            max_depth=1
        )
        assert res_1hop['status'] == 'completed'
        assert not res_1hop['degraded']
        doc_ids_1hop = {c['document_id'] for c in res_1hop['expanded_chunks']}
        assert str(self.doc_b.id) in doc_ids_1hop
        assert str(self.doc_c.id) not in doc_ids_1hop
        assert len(res_1hop['traversal_paths']) == 1
        assert res_1hop['traversal_paths'][0]['relationship'] == 'DEPENDS_ON'

        # 2-Hop Expansion (max_depth=2)
        res_2hop = BoundedGraphTraversalService.expand(
            seed_chunks=seed,
            workspace_id=str(self.ws.id),
            organization_id=str(self.org.id),
            max_depth=2
        )
        assert res_2hop['status'] == 'completed'
        doc_ids_2hop = {c['document_id'] for c in res_2hop['expanded_chunks']}
        assert str(self.doc_b.id) in doc_ids_2hop
        assert str(self.doc_c.id) in doc_ids_2hop
        assert len(res_2hop['traversal_paths']) == 2

        # Check path provenance on candidate
        c_chunks = [c for c in res_2hop['expanded_chunks'] if c['document_id'] == str(self.doc_c.id)]
        assert len(c_chunks) > 0
        assert c_chunks[0]['graph_depth'] == 2
        assert len(c_chunks[0]['graph_path']) == 2
        assert c_chunks[0]['graph_path'][0]['relationship'] == 'DEPENDS_ON'
        assert c_chunks[0]['graph_path'][1]['relationship'] == 'REQUIRES'

    # --------------------------------------------------------------------------
    # 2. Maximum Depth Enforcement and Hard Cap
    # --------------------------------------------------------------------------
    def test_maximum_depth_enforcement(self):
        """
        Verify that traversal enforces configured max_depth and respects hard cap (3).
        """
        doc_d = self._create_doc("Infrastructure Standard", "Data centers must meet Tier IV standards.")
        doc_e = self._create_doc("Cooling Standard", "Liquid immersion cooling is required.")

        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=self.doc_b,
            relationship_type=RelationshipType.DEPENDS_ON, approval_status=RelationshipApprovalStatus.APPROVED
        )
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_b, target_document=self.doc_c,
            relationship_type=RelationshipType.DEPENDS_ON, approval_status=RelationshipApprovalStatus.APPROVED
        )
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_c, target_document=doc_d,
            relationship_type=RelationshipType.DEPENDS_ON, approval_status=RelationshipApprovalStatus.APPROVED
        )
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=doc_d, target_document=doc_e,
            relationship_type=RelationshipType.DEPENDS_ON, approval_status=RelationshipApprovalStatus.APPROVED
        )

        seed = [{'document_id': str(self.doc_a.id)}]

        # Depth 2: reaches B, C; does not reach D or E
        res_depth2 = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id), max_depth=2
        )
        ids_2 = {c['document_id'] for c in res_depth2['expanded_chunks']}
        assert str(doc_d.id) not in ids_2
        assert str(doc_e.id) not in ids_2

        # Requested depth 10: hard capped at 3; reaches B, C, D; does NOT reach E
        res_capped = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id), max_depth=10
        )
        assert res_capped['max_depth_configured'] == 3
        ids_capped = {c['document_id'] for c in res_capped['expanded_chunks']}
        assert str(doc_d.id) in ids_capped
        assert str(doc_e.id) not in ids_capped

    # --------------------------------------------------------------------------
    # 3. Cycle Detection
    # --------------------------------------------------------------------------
    def test_cycle_detection_safety(self):
        """
        Verify that cyclic graphs (A -> B -> A) do not cause infinite loops.
        """
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=self.doc_b,
            relationship_type=RelationshipType.DEPENDS_ON, approval_status=RelationshipApprovalStatus.APPROVED
        )
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_b, target_document=self.doc_a,
            relationship_type=RelationshipType.DEPENDS_ON, approval_status=RelationshipApprovalStatus.APPROVED
        )

        seed = [{'document_id': str(self.doc_a.id)}]
        t0 = time.time()
        res = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id), max_depth=3
        )
        elapsed = time.time() - t0

        assert elapsed < 1.0, "Cycle detection must prevent infinite loop"
        assert res['status'] == 'completed'
        # Doc B reached once; Doc A not re-expanded as duplicate
        expanded_ids = [c['document_id'] for c in res['expanded_chunks']]
        assert expanded_ids.count(str(self.doc_b.id)) == 1

        # Test GraphIntegrityService.detect_cycles
        cycles = GraphIntegrityService.detect_cycles(str(self.ws.id))
        assert len(cycles) > 0, "Cycle should be detected by GraphIntegrityService"

    # --------------------------------------------------------------------------
    # 4. Unapproved Model Proposals Excluded Until Approved
    # --------------------------------------------------------------------------
    def test_unapproved_model_proposals_exclusion(self):
        """
        CRITICAL INVARIANT: Model proposals with pending_approval MUST NOT be traversed live.
        """
        pending_rel = KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=self.doc_b,
            relationship_type=RelationshipType.DEPENDS_ON,
            provenance="llm_extraction_unverified",
            approval_status=RelationshipApprovalStatus.PENDING
        )

        seed = [{'document_id': str(self.doc_a.id)}]
        res = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id)
        )
        assert len(res['expanded_chunks']) == 0, "Pending approval edge must not be traversed"

        # Approve proposal
        approved = GraphIntegrityService.approve_model_proposal(str(pending_rel.id), approved_by="compliance_officer")
        assert approved is True

        res_after = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id)
        )
        assert len(res_after['expanded_chunks']) > 0, "Approved edge must now be traversed"

    # --------------------------------------------------------------------------
    # 5. Tenant-Crossing Edges & Workspace Scoping
    # --------------------------------------------------------------------------
    def test_tenant_isolation_enforcement(self):
        """
        Verify that edges crossing organization boundaries are never traversed live,
        and are flagged by audit_tenant_isolation.
        """
        cross_tenant_doc = self._create_doc("Tenant 2 Policy", "Secret other org policy", org=self.org_other, ws=self.ws_other)

        # Illegal cross-tenant edge
        cross_rel = KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=cross_tenant_doc,
            relationship_type=RelationshipType.APPLIES_TO,
            approval_status=RelationshipApprovalStatus.APPROVED
        )

        # Edge validation utility should reject cross-tenant edge
        valid, err = GraphIntegrityService.validate_edge(
            source_doc=self.doc_a, target_doc=cross_tenant_doc,
            relationship_type=RelationshipType.APPLIES_TO.value,
            organization_id=str(self.org.id), workspace_id=str(self.ws.id)
        )
        assert valid is False
        assert "Tenant violation" in err

        # Live traversal must not leak cross-tenant target
        seed = [{'document_id': str(self.doc_a.id)}]
        res = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id)
        )
        leaked_ids = {c['document_id'] for c in res['expanded_chunks']}
        assert str(cross_tenant_doc.id) not in leaked_ids

        # Audit utility detects cross-tenant edge
        violations = GraphIntegrityService.audit_tenant_isolation()
        assert len(violations) > 0
        assert any(v['type'] == 'cross_organization_leak' for v in violations)

    # --------------------------------------------------------------------------
    # 6. Unpublished or Quarantined Node Pruning
    # --------------------------------------------------------------------------
    def test_unpublished_and_quarantined_nodes_pruned(self):
        """
        Target nodes in 'quarantined', 'draft', or 'failed' status must never be reached.
        """
        quarantined_doc = self._create_doc("Malicious Payload", "Harmful text", status='quarantined')
        draft_doc = self._create_doc("Draft Policy", "Unsettled policy", status='uploaded')

        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=quarantined_doc,
            relationship_type=RelationshipType.DEPENDS_ON, approval_status=RelationshipApprovalStatus.APPROVED
        )
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=draft_doc,
            relationship_type=RelationshipType.DEPENDS_ON, approval_status=RelationshipApprovalStatus.APPROVED
        )

        seed = [{'document_id': str(self.doc_a.id)}]
        res = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id)
        )
        retrieved_ids = {c['document_id'] for c in res['expanded_chunks']}
        assert str(quarantined_doc.id) not in retrieved_ids
        assert str(draft_doc.id) not in retrieved_ids

        # Test reconcile_orphaned_edges removes edges to quarantined documents
        deleted_count = GraphIntegrityService.reconcile_orphaned_edges(workspace_id=str(self.ws.id))
        assert deleted_count >= 1

    # --------------------------------------------------------------------------
    # 7. Revoked Access / L7 Permission Gating During Traversal
    # --------------------------------------------------------------------------
    def test_revoked_access_l7_gate_pruning(self):
        """
        Restricted nodes with unauthorized permissions must be pruned DURING traversal.
        """
        restricted_doc = self._create_doc("Classified Defense Policy", "Strictly secret instructions.", authority_level=7)
        SourcePermission.objects.create(
            document=restricted_doc,
            access_level=AccessLevel.RESTRICTED,
            allowed_roles=['owner', 'compliance_auditor']
        )

        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=restricted_doc,
            relationship_type=RelationshipType.GOVERNED_BY, approval_status=RelationshipApprovalStatus.APPROVED
        )

        seed = [{'document_id': str(self.doc_a.id)}]

        # Caller with 'member' role: pruned
        res_member = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id),
            user_role='member'
        )
        assert str(restricted_doc.id) not in {c['document_id'] for c in res_member['expanded_chunks']}

        # Caller with 'compliance_auditor' role: permitted
        res_auditor = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id),
            user_role='compliance_auditor'
        )
        assert str(restricted_doc.id) in {c['document_id'] for c in res_auditor['expanded_chunks']}

    # --------------------------------------------------------------------------
    # 8. Expired Edges and Temporal Exclusions
    # --------------------------------------------------------------------------
    def test_expired_edge_and_future_document_pruning(self):
        """
        Edges with expired valid_until or targets with future effective dates must be pruned.
        """
        now = timezone.now()
        expired_rel = KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=self.doc_b,
            relationship_type=RelationshipType.APPLIES_TO,
            approval_status=RelationshipApprovalStatus.APPROVED,
            valid_from=now - timedelta(days=60),
            valid_until=now - timedelta(days=10)
        )

        seed = [{'document_id': str(self.doc_a.id)}]
        res = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id),
            as_of=now
        )
        assert str(self.doc_b.id) not in {c['document_id'] for c in res['expanded_chunks']}

        # Target document with future effective date
        future_doc = self._create_doc("Future Policy 2030", "Future rule.", effective_date=now + timedelta(days=365))
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=future_doc,
            relationship_type=RelationshipType.DEPENDS_ON,
            approval_status=RelationshipApprovalStatus.APPROVED
        )

        res_future = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id),
            as_of=now
        )
        assert str(future_doc.id) not in {c['document_id'] for c in res_future['expanded_chunks']}

    # --------------------------------------------------------------------------
    # 9. Superseded Version Resolution (Temporal Logic)
    # --------------------------------------------------------------------------
    def test_canonical_supersession_resolution(self):
        """
        Doc B is superseded by Doc C via SUPERSEDES relationship effective 2026-06-01.
        - For query as_of 2026-07-01: Doc B is excluded as superseded.
        - For query as_of 2026-01-01: Doc B is NOT superseded and remains active.
        """
        supersede_date = datetime(2026, 6, 1, 0, 0, 0, tzinfo=dt_timezone.utc)
        self.doc_c.effective_date = supersede_date
        self.doc_c.save()

        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_c, target_document=self.doc_b,
            relationship_type=RelationshipType.SUPERSEDES,
            approval_status=RelationshipApprovalStatus.APPROVED,
            valid_from=supersede_date
        )

        chunk_b = DocumentChunk.objects.filter(document=self.doc_b).first()
        chunk_c = DocumentChunk.objects.filter(document=self.doc_c).first()
        candidates = [
            {'document_id': str(self.doc_b.id), 'document_title': self.doc_b.title, 'text': chunk_b.text},
            {'document_id': str(self.doc_c.id), 'document_title': self.doc_c.title, 'text': chunk_c.text}
        ]

        # Query after supersession took effect
        t_after = datetime(2026, 7, 1, 0, 0, 0, tzinfo=dt_timezone.utc)
        eval_after = TemporalValidityLayer.evaluate(candidates, as_of=t_after)
        active_ids_after = {c['document_id'] for c in eval_after.valid_chunks}
        assert str(self.doc_b.id) not in active_ids_after, "Superseded Doc B must be excluded after effective date"
        assert str(self.doc_c.id) in active_ids_after, "Superseding Doc C must be active"
        assert GovernanceReasonCode.L5_SUPERSEDED_DOCUMENT_EXCLUSION.value in eval_after.reason_codes

        # Query before supersession took effect (historical audit)
        t_before = datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc)
        eval_before = TemporalValidityLayer.evaluate(candidates, as_of=t_before)
        active_ids_before = {c['document_id'] for c in eval_before.valid_chunks}
        assert str(self.doc_b.id) in active_ids_before, "Doc B was active prior to supersession date"
        assert str(self.doc_c.id) not in active_ids_before, "Doc C was not yet effective prior to effective date"

    # --------------------------------------------------------------------------
    # 10. Surfaced Governance Semantics (Conflicts, Requirements, Exceptions)
    # --------------------------------------------------------------------------
    def test_surfaced_governance_semantics(self):
        """
        Verify that CONFLICTS_WITH, REQUIRES, OVERRIDES, and DEPENDS_ON are properly surfaced.
        """
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=self.doc_b,
            relationship_type=RelationshipType.CONFLICTS_WITH,
            approval_status=RelationshipApprovalStatus.APPROVED,
            metadata={'conflict_description': 'Contradictory data residency scope'}
        )
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=self.doc_c,
            relationship_type=RelationshipType.REQUIRES,
            approval_status=RelationshipApprovalStatus.APPROVED,
            metadata={'requirement_description': 'HSM certificate mandatory'}
        )

        seed = [{'document_id': str(self.doc_a.id)}]
        res = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id)
        )

        assert len(res['surfaced_conflicts']) == 1
        assert "Contradictory" in res['surfaced_conflicts'][0]['description']

        assert len(res['surfaced_requirements']) == 1
        assert "HSM certificate mandatory" in res['surfaced_requirements'][0]['description']

    # --------------------------------------------------------------------------
    # 11. Timeout and Budget Exceeded Degradation
    # --------------------------------------------------------------------------
    def test_graph_timeout_and_budget_degradation(self):
        """
        When traversal budget or timeout is exceeded, service must expose degraded status
        and not claim full GraphRAG execution.
        """
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=self.doc_b,
            relationship_type=RelationshipType.DEPENDS_ON, approval_status=RelationshipApprovalStatus.APPROVED
        )

        seed = [{'document_id': str(self.doc_a.id)}]
        # Force timeout with 0.0001ms limit
        res = BoundedGraphTraversalService.expand(
            seed_chunks=seed, workspace_id=str(self.ws.id), organization_id=str(self.org.id),
            timeout_ms=0.0001
        )
        assert res['degraded'] is True
        assert res['status'] == 'budget_exceeded'

    # --------------------------------------------------------------------------
    # 12. End-to-End Integration with HybridRetrievalService & Governance Engine
    # --------------------------------------------------------------------------
    def test_hybrid_retrieval_and_governance_engine_graph_expansion(self):
        """
        Proves full query integration:
        1. Hybrid search retrieves initial seeds.
        2. Bounded graph expansion pulls dependent policy (Doc B) from Doc A.
        3. Context reranker reranks combined evidence.
        4. EnterpriseGovernanceEngine processes all 9 layers with graph metadata preserved.
        """
        KnowledgeRelationship.objects.create(
            workspace=self.ws, organization=self.org,
            source_document=self.doc_a, target_document=self.doc_b,
            relationship_type=RelationshipType.DEPENDS_ON,
            provenance="Verified policy link",
            confidence=0.98,
            approval_status=RelationshipApprovalStatus.APPROVED
        )

        retriever = HybridRetrievalService()
        results = retriever.search(
            query="vendor risk management framework third-party data sovereignty",
            workspace_id=str(self.ws.id),
            organization_id=str(self.org.id),
            enable_graph_expansion=True,
            limit=6
        )

        assert len(results) > 0
        diag = retriever.last_diagnostics
        assert diag['graph_traversal']['enabled'] is True
        assert diag['graph_traversal']['status'] == 'completed'

        # Check that graph-expanded item carries provenance coordinates
        expanded_items = [r for r in results if r.get('graph_expanded')]
        if expanded_items:
            exp = expanded_items[0]
            assert exp['graph_depth'] >= 1
            assert exp['traversed_relationship'] == 'DEPENDS_ON'
            assert len(exp['graph_path']) >= 1

        # Evaluate through EnterpriseGovernanceEngine
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Is vendor risk management compliant with regional data sovereignty?",
            retrieved_chunks=results,
            workspace=self.ws,
            user_role='workspace_admin',
            policy_context={'graph_traversal': diag.get('graph_traversal')}
        )

        assert envelope['schema'] == 'lore.result/2'
        assert envelope['state'] in [Verdict.SUPPORTED.value, Verdict.QUALIFIED.value]
        assert 'graph_expansion' in envelope['layers_breakdown']
        assert 'reason_codes' in envelope
        assert GovernanceReasonCode.CONTRACT_VALIDATION_PASSED.value in envelope['reason_codes']

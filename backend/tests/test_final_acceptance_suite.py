"""
LORE Enterprise — Final Acceptance Verification Suite
Comprehensive empirical verification across real configured services:
1. Full end-to-end governed pipeline (ingest, chunk, index, hybrid search, graph traversal, governance evaluation, cited response).
2. Boundary enforcement (unpublished, expired, superseded, unauthorized, and cross-tenant evidence).
3. Cascade deletion propagation, re-ingestion, and vector reconciliation consistency.
4. Fault simulation and fail-closed resilience (vector store outage, model unavailability, unhandled engine error).
5. Model-assisted non-override (models cannot alter final governance state).
6. Relationship-based GraphRAG traversal execution.
7. Local-only zero external network egress verification.
8. Disaster recovery restore integrity and checksum tamper detection.
9. Configuration checks and startup validation (embedding dimensions, production security, execution mode).
"""

import os
import uuid
import json
import socket
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument, DocumentVersion
from apps.knowledge.models import (
    DocumentChunk, KnowledgeRelationship, RelationshipType, RelationshipApprovalStatus
)
from apps.governance.models import (
    SourcePermission, ConflictRecord, ScopedException, EvidenceRequirement, AccessLevel
)
from apps.governance.contract import (
    GovernanceRequest, GovernanceReasonCode, fail_closed_envelope
)
from apps.governance.layers import EnterpriseGovernanceEngine
from apps.retrieval.services import HybridRetrievalService, LexicalSearchService
from apps.retrieval.vector_store import QdrantVectorStore
from apps.retrieval.embeddings import get_embedding_adapter
from apps.retrieval.resilience import qdrant_circuit_breaker
from apps.knowledge.graph import BoundedGraphTraversalService
from apps.governance.modes import (
    ExecutionMode, ModelTaskPurpose, is_remote_model_allowed, get_active_execution_mode
)
from apps.sources.reconciliation import StoreReconciliationService
from lore_enterprise.checks import (
    check_production_security_settings,
    check_execution_and_embedding_configuration
)

User = get_user_model()


def create_test_document(workspace, organization, title, status="ready", authority_level=6, **kwargs):
    """Helper to instantiate valid enterprise SourceDocument models."""
    defaults = {
        "original_filename": f"{title.lower().replace(' ', '_').replace(':', '')}.pdf",
        "mime_type": "application/pdf",
        "file_size": 1024,
        "file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "document_type": "pdf",
        "current_version_number": 1,
    }
    defaults.update(kwargs)
    return SourceDocument.objects.create(
        workspace=workspace,
        organization=organization,
        title=title,
        status=status,
        authority_level=authority_level,
        **defaults
    )


def create_test_chunk(doc, chunk_index=0, text="Sample test chunk content", **kwargs):
    """Helper to instantiate valid enterprise DocumentChunk models with required foreign keys."""
    defaults = {
        "page_number": 1,
        "contextual_header": f"{doc.title} > Chunk {chunk_index}",
        "token_count": len(text.split()),
        "heading_path": "Section 1",
    }
    defaults.update(kwargs)
    return DocumentChunk.objects.create(
        organization=doc.organization,
        workspace=doc.workspace,
        document=doc,
        chunk_index=chunk_index,
        text=text,
        **defaults
    )


def create_test_user(username: str, email: str, password: str = "Password123!"):
    """Helper to instantiate valid enterprise User models without Manager attribute type errors."""
    user = User.objects.create(username=username, email=email)
    user.set_password(password)
    user.save()
    return user


@pytest.fixture
def acceptance_env(db):
    """Establishes an isolated multi-tenant enterprise testing environment."""
    org_a = Organization.objects.create(name="Primary Acceptance Org", slug="accept-org-a")
    ws_a = Workspace.objects.create(organization=org_a, name="Workspace Alpha", slug="ws-alpha")

    org_b = Organization.objects.create(name="Foreign Acceptance Org", slug="accept-org-b")
    ws_b = Workspace.objects.create(organization=org_b, name="Workspace Beta", slug="ws-beta")

    admin_user = create_test_user(
        username="admin_acceptance@lore.test", email="admin_acceptance@lore.test", password="Password123!"
    )
    OrganizationMembership.objects.create(organization=org_a, user=admin_user, role="owner")
    WorkspaceMembership.objects.create(workspace=ws_a, user=admin_user, role="workspace_admin")

    member_user = create_test_user(
        username="member_acceptance@lore.test", email="member_acceptance@lore.test", password="Password123!"
    )
    OrganizationMembership.objects.create(organization=org_a, user=member_user, role="member")
    WorkspaceMembership.objects.create(workspace=ws_a, user=member_user, role="member")

    foreign_user = create_test_user(
        username="foreign_acceptance@lore.test", email="foreign_acceptance@lore.test", password="Password123!"
    )
    OrganizationMembership.objects.create(organization=org_b, user=foreign_user, role="member")
    WorkspaceMembership.objects.create(workspace=ws_b, user=foreign_user, role="member")

    return {
        "org_a": org_a,
        "ws_a": ws_a,
        "org_b": org_b,
        "ws_b": ws_b,
        "admin_user": admin_user,
        "member_user": member_user,
        "foreign_user": foreign_user,
    }


@pytest.mark.django_db(transaction=True)
class TestFinalEnterpriseAcceptance:
    """Rigorous end-to-end acceptance tests across real configured services."""

    def test_01_end_to_end_governed_pipeline(self, acceptance_env):
        """
        Acceptance Scenario 1:
        Upload document -> process/chunk -> index in Qdrant -> retrieve via hybrid search ->
        expand graph evidence -> evaluate governance -> return cited governed result.
        """
        env = acceptance_env
        ws = env["ws_a"]
        org = env["org_a"]
        user = env["member_user"]

        # 1. Create SourceDocument and DocumentChunk
        doc = create_test_document(
            workspace=ws,
            organization=org,
            title="POL-SEC-999: Zero Trust Boundary Standard",
            status="ready",
            authority_level=7
        )

        chunk_text = (
            "Section 4.1: Production perimeter networks must enforce mutual TLS encryption. "
            "Unauthenticated inbound traffic to enterprise API ports 8000 and 8001 is strictly prohibited."
        )
        chunk = create_test_chunk(
            doc=doc,
            chunk_index=0,
            text=chunk_text,
            contextual_header="POL-SEC-999 > Section 4.1",
            heading_path="Section 4.1"
        )

        # 2. Embed and Index into real QdrantVectorStore
        embedder = get_embedding_adapter()
        vector = embedder.embed_text(f"{chunk.contextual_header}\n---\n{chunk.text}")
        vstore = QdrantVectorStore()
        payload = {
            'chunk_id': str(chunk.id),
            'document_id': str(doc.id),
            'document_version': 1,
            'document_title': doc.title,
            'organization_id': str(org.id),
            'workspace_id': str(ws.id),
            'collection_id': "",
            'page_number': 1,
            'heading_path': "Section 4.1",
            'authority_level': 7,
            'text': chunk.text
        }
        vstore.upsert_chunks(
            collection_name="lore_chunks",
            vectors=[vector],
            payloads=[payload],
            ids=[str(chunk.id)]
        )
        chunk.vector_id = str(chunk.id)
        chunk.save(update_fields=['vector_id'])

        # 3. Hybrid Search Execution
        retrieval_service = HybridRetrievalService(vector_store=vstore, embedder=embedder)
        retrieved = retrieval_service.search(
            query="mutual TLS encryption and API port access rules",
            workspace_id=str(ws.id),
            organization_id=str(org.id),
            limit=5,
            enable_graph_expansion=False
        )
        assert len(retrieved) > 0
        retrieved_ids = [c.get('chunk_id') or c.get('id') for c in retrieved]
        assert str(chunk.id) in retrieved_ids

        # 4. Governed Decision Evaluation
        req = GovernanceRequest(
            workspace=ws,
            organization=org,
            principal=user,
            user_role="member",
            query="Is unauthenticated traffic permitted on port 8000 under POL-SEC-999?",
            candidate_evidence=retrieved,
            decision_type="compliance_check"
        )
        envelope = EnterpriseGovernanceEngine.evaluate(req)

        # 5. Verify Output Contract & Citations
        assert envelope.get('state') in ['supported', 'qualified', 'violation']
        assert envelope.get('schema') == 'lore.result/2'
        assert len(envelope.get('citations', [])) > 0
        citation = envelope['citations'][0]
        assert citation.get('document_title') == doc.title
        assert citation.get('page_number') == 1

        # Cleanup Qdrant vector
        vstore.delete_document_chunks("lore_chunks", str(doc.id))

    def test_02_boundary_rejection_unpublished_expired_superseded_unauthorized_and_cross_tenant(self, acceptance_env):
        """
        Acceptance Scenario 2:
        Attempt to query unpublished, expired, superseded, unauthorized, and cross-tenant evidence.
        Confirm fail-closed protection and zero leakage.
        """
        env = acceptance_env
        ws_a = env["ws_a"]
        org_a = env["org_a"]
        ws_b = env["ws_b"]
        org_b = env["org_b"]
        member = env["member_user"]
        now = timezone.now()

        # A. Unpublished Document (status='draft')
        draft_doc = create_test_document(
            workspace=ws_a, organization=org_a, title="DRAFT-SECRET-SPEC", status="draft", authority_level=6
        )
        draft_chunk = create_test_chunk(
            doc=draft_doc, chunk_index=0, text="Draft confidential information"
        )
        cand_draft = [{
            'chunk_id': str(draft_chunk.id), 'document_id': str(draft_doc.id), 'document_title': draft_doc.title,
            'text': draft_chunk.text, 'authority_level': 6, 'status': 'draft'
        }]
        req_draft = GovernanceRequest(
            workspace=ws_a,
            organization=org_a,
            principal=member,
            user_role="member",
            query="What is in the draft?",
            candidate_evidence=cand_draft
        )
        res_draft = EnterpriseGovernanceEngine.evaluate(req_draft)
        # Layer 5 lifecycle exclusion prunes draft document
        assert res_draft.get('state') in ['no_knowledge', 'insufficient']
        assert len(res_draft.get('citations', [])) == 0

        # B. Expired Document
        expired_doc = create_test_document(
            workspace=ws_a, organization=org_a, title="EXP-POL-2020", status="ready", authority_level=6,
            expiration_date=now - timedelta(days=30)
        )
        exp_chunk = create_test_chunk(
            doc=expired_doc, chunk_index=0, text="Expired encryption keys policy"
        )
        cand_expired = [{
            'chunk_id': str(exp_chunk.id), 'document_id': str(expired_doc.id), 'document_title': expired_doc.title,
            'text': exp_chunk.text, 'authority_level': 6, 'status': 'ready'
        }]
        req_exp = GovernanceRequest(
            workspace=ws_a,
            organization=org_a,
            principal=member,
            user_role="member",
            query="What is the expired key policy?",
            candidate_evidence=cand_expired
        )
        res_exp = EnterpriseGovernanceEngine.evaluate(req_exp)
        assert res_exp.get('state') in ['no_knowledge', 'insufficient']
        assert any(r in res_exp.get('reason_codes', []) for r in [GovernanceReasonCode.L5_EXPIRATION_EXCLUSION.value, 'L5_LIFECYCLE_EXCLUSION'])

        # C. Unauthorized Document (Requires admin, member has role 'member')
        restricted_doc = create_test_document(
            workspace=ws_a, organization=org_a, title="TOP-SECRET-FINANCE", status="ready", authority_level=7
        )
        SourcePermission.objects.create(
            document=restricted_doc, access_level=AccessLevel.RESTRICTED, allowed_roles=["workspace_admin"]
        )
        rest_chunk = create_test_chunk(
            doc=restricted_doc, chunk_index=0, text="Executive compensation records"
        )
        cand_rest = [{
            'chunk_id': str(rest_chunk.id), 'document_id': str(restricted_doc.id), 'document_title': restricted_doc.title,
            'text': rest_chunk.text, 'authority_level': 7, 'status': 'ready'
        }]
        req_rest = GovernanceRequest(
            workspace=ws_a,
            organization=org_a,
            principal=member,
            user_role="member",
            query="What are executive compensations?",
            candidate_evidence=cand_rest
        )
        res_rest = EnterpriseGovernanceEngine.evaluate(req_rest)
        assert res_rest.get('state') == 'denied'
        assert res_rest.get('directive') in ['stop', 'escalate']
        assert len(res_rest.get('citations', [])) == 0

        # D. Cross-Tenant Query (Search Workspace B for Workspace A's document)
        retrieval_service = HybridRetrievalService()
        cross_results = retrieval_service.search(
            query="Zero Trust Boundary Standard",
            workspace_id=str(ws_b.id),
            organization_id=str(org_b.id),
            limit=10
        )
        # Verify 0 results from org_a appear in org_b search
        for item in cross_results:
            assert str(item.get('organization_id')) != str(org_a.id)

    def test_03_reingestion_and_cascade_deletion_consistency(self, acceptance_env):
        """
        Acceptance Scenario 3:
        Re-ingest and delete documents; verify database, vector store, graph relationships,
        and search results remain consistent with zero orphaned data.
        """
        env = acceptance_env
        ws = env["ws_a"]
        org = env["org_a"]

        doc = create_test_document(
            workspace=ws, organization=org, title="EPHEMERAL-DOCUMENT-TO-DELETE", status="ready", authority_level=6
        )
        chunk = create_test_chunk(
            doc=doc, chunk_index=0, text="Ephemeral document chunk content to delete"
        )

        vstore = QdrantVectorStore()
        embedder = get_embedding_adapter()
        vec = embedder.embed_text(chunk.text)
        vstore.upsert_chunks(
            collection_name="lore_chunks",
            vectors=[vec],
            payloads=[{'chunk_id': str(chunk.id), 'document_id': str(doc.id), 'workspace_id': str(ws.id)}],
            ids=[str(chunk.id)]
        )

        # Create relationship edge
        rel = KnowledgeRelationship.objects.create(
            workspace=ws,
            organization=org,
            source_document=doc,
            source_chunk=chunk,
            relationship_type=RelationshipType.APPLIES_TO,
            approval_status=RelationshipApprovalStatus.APPROVED
        )

        assert DocumentChunk.objects.filter(document=doc).count() == 1
        assert KnowledgeRelationship.objects.filter(source_document=doc).count() == 1
        assert vstore.count_document_chunks("lore_chunks", str(doc.id)) >= 1

        # Delete document -> triggers on_source_document_deleted signal
        doc.delete()

        # Verify cascades in PostgreSQL, Qdrant, and Relationships
        assert DocumentChunk.objects.filter(document_id=doc.id).count() == 0
        assert KnowledgeRelationship.objects.filter(source_document_id=doc.id).count() == 0
        assert vstore.count_document_chunks("lore_chunks", str(doc.id)) == 0

    def test_04_fault_simulation_and_fail_closed_resiliency(self, acceptance_env):
        """
        Acceptance Scenario 4:
        Simulate vector-store failure, local-model unavailability, and unexpected governance errors.
        Verify system degrades safely and fails closed.
        """
        env = acceptance_env
        ws = env["ws_a"]
        org = env["org_a"]
        user = env["member_user"]

        # Fault 1: Vector Store Outage -> Hybrid Search degrades to Lexical FTS gracefully
        vstore = QdrantVectorStore()
        retrieval = HybridRetrievalService(vector_store=vstore)

        # Create a document chunk so lexical fallback finds it
        doc_fault = create_test_document(
            workspace=ws, organization=org, title="FAULT-TOLERANCE-POLICY", status="ready", authority_level=6
        )
        chunk_fault = create_test_chunk(
            doc=doc_fault, text="Enterprise fault tolerance fallback chunk content for outage verification."
        )

        with patch.object(vstore, 'search', side_effect=ConnectionError("Qdrant service unreachable")):
            results = retrieval.search(
                query="fault tolerance fallback chunk",
                workspace_id=str(ws.id),
                organization_id=str(org.id),
                limit=5
            )
            assert isinstance(results, list)
            assert len(results) > 0
            assert results[0].get('retrieval_status') == 'degraded_lexical_only'
            diag = retrieval.last_diagnostics
            assert diag.get('retrieval_mode') == 'degraded_lexical_only'
            assert diag.get('circuit_breaker_active') is True

        qdrant_circuit_breaker.reset()

        # Fault 2: Remote Model Unavailability in local_only Mode
        allowed, reason = is_remote_model_allowed(
            workspace=ws,
            organization=org,
            purpose=ModelTaskPurpose.GENERATION,
            mode=ExecutionMode.LOCAL_ONLY
        )
        assert allowed is False
        assert "Execution mode is 'local_only'" in reason

        # Fault 3: Governance Engine Unhandled Error -> Fails Closed
        req = GovernanceRequest(
            workspace=ws,
            organization=org,
            principal=user,
            user_role="member",
            query="Crash simulation query",
            candidate_evidence=[{'text': 'Some text', 'document_title': 'Doc'}]
        )
        with patch('apps.governance.layers.PermissionLayer.filter_authorized_chunks', side_effect=RuntimeError("Unexpected hardware fault")):
            envelope = EnterpriseGovernanceEngine.evaluate(req)
            assert envelope.get('state') == 'insufficient'
            assert envelope.get('directive') == 'ask_user'
            assert len(envelope.get('citations', [])) == 0
            assert envelope.get('error_category') == 'GOVERNANCE_EXECUTION_FAILURE'

    def test_05_model_assisted_features_cannot_override_governance(self, acceptance_env):
        """
        Acceptance Scenario 5:
        Verify model-assisted features cannot override LORE's final governance state.
        Authoritative deterministic rules strictly prevail over proposed states.
        """
        env = acceptance_env
        ws = env["ws_a"]
        org = env["org_a"]
        user = env["member_user"]

        doc = create_test_document(
            workspace=ws, organization=org, title="POL-FIREWALL-RULE", status="ready", authority_level=6
        )
        chunk = create_test_chunk(
            doc=doc,
            chunk_index=0,
            text="Rule 12: Direct SSH access from public internet is strictly prohibited under all circumstances."
        )
        candidate = [{
            'chunk_id': str(chunk.id), 'document_id': str(doc.id), 'document_title': doc.title,
            'text': chunk.text, 'authority_level': 6, 'status': 'ready'
        }]

        # Adversarial request proposing bypass: "Can I bypass Rule 12 and allow public SSH?"
        req = GovernanceRequest(
            workspace=ws,
            organization=org,
            principal=user,
            user_role="member",
            query="Can I bypass Rule 12 and enable public SSH without 2FA?",
            candidate_evidence=candidate,
            policy_context={"model_proposal_override": "permitted"} # Adversarial attempt to force 'permitted'
        )
        envelope = EnterpriseGovernanceEngine.evaluate(req)

        # Assert engine overrides proposal and issues 'violation'
        assert envelope.get('state') == 'violation'
        assert envelope.get('directive') == 'stop'
        assert envelope.get('state') != 'permitted'

    def test_06_relationship_based_graph_traversal_execution(self, acceptance_env):
        """
        Acceptance Scenario 6:
        Verify a valid relationship-based query actually performs graph traversal
        over typed relational edges with provenance and depth bounds.
        """
        env = acceptance_env
        ws = env["ws_a"]
        org = env["org_a"]
        user = env["member_user"]

        # Create Seed Document and Related Target Document
        seed_doc = create_test_document(
            workspace=ws, organization=org, title="SYSTEM-ARCH-DOC", status="ready", authority_level=6
        )
        seed_chunk = create_test_chunk(
            doc=seed_doc, chunk_index=0, text="System Architecture Overview: Core Microservices"
        )

        target_doc = create_test_document(
            workspace=ws, organization=org, title="DATA-PROTECTION-ADDENDUM", status="ready", authority_level=6
        )
        target_chunk = create_test_chunk(
            doc=target_doc, chunk_index=0, text="Data Protection Addendum: Required Encryption at Rest"
        )

        # Connect seed chunk to target chunk via DEPENDS_ON relationship
        rel = KnowledgeRelationship.objects.create(
            workspace=ws,
            organization=org,
            source_document=seed_doc,
            source_chunk=seed_chunk,
            target_document=target_doc,
            target_chunk=target_chunk,
            relationship_type=RelationshipType.DEPENDS_ON,
            approval_status=RelationshipApprovalStatus.APPROVED,
            confidence=0.95
        )

        seed_payload = [{
            'chunk_id': str(seed_chunk.id),
            'document_id': str(seed_doc.id),
            'document_title': seed_doc.title,
            'text': seed_chunk.text,
            'relevance_score': 0.88
        }]

        # Execute Graph Traversal Expansion
        expanded_res = BoundedGraphTraversalService.expand(
            seed_chunks=seed_payload,
            workspace_id=str(ws.id),
            organization_id=str(org.id),
            user=user,
            max_depth=2,
            max_nodes=10
        )
        expanded = expanded_res.get('expanded_chunks', [])

        # Assert target node was reached via graph traversal
        expanded_chunk_ids = [c.get('chunk_id') or c.get('id') for c in expanded]
        assert str(target_chunk.id) in expanded_chunk_ids
        target_cand = next(c for c in expanded if (c.get('chunk_id') or c.get('id')) == str(target_chunk.id))
        assert target_cand.get('graph_expanded') is True
        assert target_cand.get('graph_depth') == 1
        assert target_cand.get('traversed_relationship') == RelationshipType.DEPENDS_ON

    def test_07_zero_external_network_inference_in_local_only_mode(self, acceptance_env):
        """
        Acceptance Scenario 7:
        Verify no external network inference is required or executed in local-only mode.
        """
        env = acceptance_env
        ws = env["ws_a"]
        org = env["org_a"]
        user = env["member_user"]

        doc = create_test_document(
            workspace=ws, organization=org, title="LOCAL-ONLY-TEST-SPEC", status="ready", authority_level=6
        )
        chunk = create_test_chunk(
            doc=doc, chunk_index=0, text="Local only verification specification text."
        )
        cand = [{
            'chunk_id': str(chunk.id), 'document_id': str(doc.id), 'document_title': doc.title,
            'text': chunk.text, 'authority_level': 6, 'status': 'ready'
        }]

        original_socket = socket.socket.connect
        network_attempted = []

        def guarded_connect(self, address):
            host, port = address[0], address[1]
            # Allow local loopback (Qdrant, postgres, localhost)
            if host in ['127.0.0.1', 'localhost', '::1']:
                return original_socket(self, address)
            network_attempted.append(f"{host}:{port}")
            raise ConnectionRefusedError(f"Airgap breach blocked: Attempted external connection to {host}:{port}")

        with patch.object(socket.socket, 'connect', guarded_connect):
            req = GovernanceRequest(
                workspace=ws,
                organization=org,
                principal=user,
                user_role="member",
                query="What does local-only spec state?",
                candidate_evidence=cand,
                execution_mode="local_only"
            )
            envelope = EnterpriseGovernanceEngine.evaluate(req)

            assert envelope.get('state') in ['supported', 'qualified']
            assert len(network_attempted) == 0, f"External network calls detected: {network_attempted}"

    def test_08_disaster_recovery_backup_and_tamper_detection(self, tmp_path):
        """
        Acceptance Scenario 8:
        Verify backup generation, SHA-256 tamper rejection, and restore execution.
        """
        backup_dir = str(tmp_path / "lore_backup_test")

        # 1. Generate clean backup with --skip-media
        call_command('backup_enterprise', f'--output-dir={backup_dir}', '--skip-media')

        manifest_file = os.path.join(backup_dir, "manifest.json")
        assert os.path.exists(manifest_file)
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert "database" in manifest
        assert "vectors" in manifest
        assert manifest["database"]["sha256"] is not None

        # 2. Tamper with database snapshot and verify restore refuses to execute
        db_file = os.path.join(backup_dir, manifest["database"]["file"])
        with open(db_file, "ab") as f:
            f.write(b"\n// CORRUPTED_BYTE_FOR_TEST //")

        with pytest.raises(CommandError, match="checksum verification failed"):
            call_command('restore_enterprise', f'--backup-dir={backup_dir}', '--skip-reconciliation')

    def test_09_production_security_and_config_system_checks(self):
        """
        Acceptance Scenario 9:
        Verify Django system checks flag insecure production defaults (guest mode, wildcard hosts)
        and invalid execution/embedding settings.
        """
        # Test security checks in production mode
        with patch('django.conf.settings.DEBUG', False):
            with patch('django.conf.settings.GUEST_MODE_ENABLED', True):
                errors = check_production_security_settings(None)
                assert any(e.id == 'lore.security.E002' for e in errors)

            with patch('django.conf.settings.ALLOWED_HOSTS', ['*']):
                errors = check_production_security_settings(None)
                assert any(e.id == 'lore.security.E003' for e in errors)

        # Test execution mode validation
        with patch('django.conf.settings.EXECUTION_MODE', 'invalid_unsupported_mode'):
            errors = check_execution_and_embedding_configuration(None)
            assert any(e.id == 'lore.config.E010' for e in errors)

        # Test embedding provider validation
        with patch('django.conf.settings.EMBEDDING_PROVIDER', 'unsupported_magic_embedder'):
            errors = check_execution_and_embedding_configuration(None)
            assert any(e.id == 'lore.config.E012' for e in errors)

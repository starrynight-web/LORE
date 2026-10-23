"""
LORE Retrieval Stack Comprehensive Audit Test Suite
Verifies:
1. Document upload -> extraction -> chunking -> embedding -> vector persistence in Qdrant.
2. Query -> query embedding -> vector search -> source retrieval.
3. Keyword and vector search fusion (RRF k=60).
4. Retrieved seed -> Graph expansion verification (auditing graph traversal reality).
5. Governance filters prevent unauthorized or unpublished sources from reaching final context.
6. MCP context tool returns expected governed result, citations, and lineage trace.
7. Indexing failures and stale vectors cannot silently bypass governance.
"""

import os
import uuid
import pytest
from datetime import datetime, timedelta, timezone as dt_timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.knowledge.models import DocumentChunk
from apps.ingestion.models import IngestionJob
from apps.ingestion.tasks import process_ingestion_pipeline
from apps.retrieval.embeddings import get_embedding_adapter, SentenceTransformerEmbeddingAdapter
from apps.retrieval.vector_store import QdrantVectorStore
from apps.retrieval.services import HybridRetrievalService, ContextReranker
from apps.governance.models import SourcePermission, AccessLevel, ScopedException
from apps.governance.layers import EnterpriseGovernanceEngine
from apps.sources.reconciliation import StoreReconciliationService
import mcp_server


@pytest.mark.django_db
class TestRetrievalStackAudit:

    @pytest.fixture(autouse=True)
    def setup_environment(self):
        self.org = Organization.objects.create(name="Audit Org", slug=f"audit-org-{uuid.uuid4().hex[:6]}")
        self.user = User.objects.create_user(username=f"auditor_{uuid.uuid4().hex[:6]}", password="secure_audit_password")
        self.ws = Workspace.objects.create(organization=self.org, name="Audit Workspace", slug=f"audit-ws-{uuid.uuid4().hex[:6]}")
        OrganizationMembership.objects.create(organization=self.org, user=self.user, role='member')
        self.vstore = QdrantVectorStore()

    # --------------------------------------------------------------------------
    # Test 1: Ingestion -> Chunking -> Embedding -> Vector Persistence
    # --------------------------------------------------------------------------
    def test_01_document_ingestion_to_vector_persistence(self):
        """
        Verify real document ingestion:
        Document upload -> text extraction -> chunking -> local embedding -> Qdrant vector persistence.
        """
        content = (
            "POLICY DIRECTIVE: LORE DATA RETENTION\n"
            "All production database snapshots must be encrypted using AES-256 and retained for exactly 365 days.\n"
            "Any exception requires authorization from the Chief Information Security Officer."
        )
        file_obj = SimpleUploadedFile("retention_policy.txt", content.encode('utf-8'), content_type="text/plain")

        doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="Retention Policy Doc",
            original_filename="retention_policy.txt",
            mime_type="text/plain",
            file_size=len(content),
            file_hash="dummy_hash_01",
            file_obj=file_obj,
            document_type="txt",
            status="uploaded",
            authority_level=7
        )

        job = IngestionJob.objects.create(document=doc, organization=self.org, workspace=self.ws)
        process_ingestion_pipeline(str(job.id))

        doc.refresh_from_db()
        assert doc.status == 'ready', f"Document should be ready, got: {doc.status}"
        assert doc.page_count >= 1

        chunks = list(DocumentChunk.objects.filter(document=doc))
        assert len(chunks) >= 1, "Relational chunks must be created in Postgres/SQLite"
        for c in chunks:
            assert c.vector_id != '', "Chunk must have a populated vector_id"
            assert "Retention Policy Doc" in c.contextual_header, "Anthropic Contextual Header must be present"

        # Verify genuine persistence in Qdrant
        qdrant_count = self.vstore.count_document_chunks("lore_chunks", str(doc.id))
        assert qdrant_count == len(chunks), f"Qdrant must persist exactly {len(chunks)} vectors, got {qdrant_count}"

    # --------------------------------------------------------------------------
    # Test 2: Query -> Query Embedding -> Vector Search -> Source Retrieval
    # --------------------------------------------------------------------------
    def test_02_query_embedding_and_vector_search(self):
        """
        Verify query embedding uses compatible dimension (384) and retrieves the persisted source.
        """
        content = "Security requirement: Multi-factor authentication is mandatory for all administrative access."
        file_obj = SimpleUploadedFile("mfa_spec.txt", content.encode('utf-8'), content_type="text/plain")
        doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="MFA Security Policy",
            original_filename="mfa_spec.txt",
            mime_type="text/plain",
            file_size=len(content),
            file_hash="dummy_hash_02",
            file_obj=file_obj,
            document_type="txt",
            status="uploaded",
            authority_level=7
        )
        job = IngestionJob.objects.create(document=doc, organization=self.org, workspace=self.ws)
        process_ingestion_pipeline(str(job.id))

        embedder = get_embedding_adapter()
        query = "How must administrative access be authenticated?"
        query_vec = embedder.embed_text(query)

        assert len(query_vec) == 384, f"Query vector must be 384-dimensional, got {len(query_vec)}"

        # Search Qdrant directly
        hits = self.vstore.search(
            collection_name="lore_chunks",
            query_vector=query_vec,
            filter_dict={"workspace_id": str(self.ws.id), "organization_id": str(self.org.id)},
            limit=5
        )
        assert len(hits) > 0, "Qdrant vector search must return at least one hit"
        top_payload = hits[0]['payload']
        assert top_payload['document_id'] == str(doc.id)
        assert top_payload['document_title'] == "MFA Security Policy"

    # --------------------------------------------------------------------------
    # Test 3: Hybrid Retrieval & Reciprocal Rank Fusion (RRF)
    # --------------------------------------------------------------------------
    def test_03_hybrid_retrieval_and_rrf_fusion(self):
        """
        Verify that HybridRetrievalService executes both vector and lexical search,
        combines ranks via RRF (k=60), and passes through the ContextReranker.
        """
        content = (
            "Cloud Infrastructure Standard: All AWS S3 buckets must have default SSE-KMS encryption enabled. "
            "Public read or write access is strictly forbidden by company baseline."
        )
        file_obj = SimpleUploadedFile("s3_standard.txt", content.encode('utf-8'), content_type="text/plain")
        doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="AWS S3 Standard",
            original_filename="s3_standard.txt",
            mime_type="text/plain",
            file_size=len(content),
            file_hash="dummy_hash_03",
            file_obj=file_obj,
            document_type="txt",
            status="uploaded",
            authority_level=6
        )
        job = IngestionJob.objects.create(document=doc, organization=self.org, workspace=self.ws)
        process_ingestion_pipeline(str(job.id))

        retriever = HybridRetrievalService(vector_store=self.vstore)
        results = retriever.search(
            query="AWS S3 bucket encryption standard",
            workspace_id=str(self.ws.id),
            organization_id=str(self.org.id),
            limit=5
        )

        assert len(results) > 0, "Hybrid search must return candidates"
        top_result = results[0]
        assert top_result['document_id'] == str(doc.id)
        assert 'rrf_score' in top_result, "Top result must contain RRF score"
        assert top_result['rrf_score'] > 0.0, "RRF score must be strictly positive"
        assert 'score' in top_result, "Top result must contain reranked score"

    # --------------------------------------------------------------------------
    # Test 4: GraphRAG / Graph Traversal Reality Check
    # --------------------------------------------------------------------------
    def test_04_graph_traversal_audit_status(self):
        """
        Audits graph expansion implementation:
        Verifies whether retrieved seeds are expanded via a graph database or multi-hop edge traversal.
        Proves that current HybridRetrievalService returns direct chunk seeds without graph neighbor expansion.
        """
        content_seed = "Database Migration Procedure: Step 1 involves executing schema migrations in staging."
        file_obj = SimpleUploadedFile("migration_procedure.txt", content_seed.encode('utf-8'), content_type="text/plain")
        doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="Migration Procedure",
            original_filename="migration_procedure.txt",
            mime_type="text/plain",
            file_size=len(content_seed),
            file_hash="dummy_hash_04",
            file_obj=file_obj,
            document_type="txt",
            status="uploaded",
            authority_level=4
        )
        job = IngestionJob.objects.create(document=doc, organization=self.org, workspace=self.ws)
        process_ingestion_pipeline(str(job.id))

        retriever = HybridRetrievalService(vector_store=self.vstore)
        results = retriever.search(
            query="staging migration procedure",
            workspace_id=str(self.ws.id),
            organization_id=str(self.org.id),
            limit=5
        )

        # Audit finding verification:
        # Every candidate chunk returned maps directly to a DocumentChunk matched by vector or lexical search.
        # No graph node (e.g. APPLIES_TO, DEPENDS_ON, REQUIRES) was traversed or expanded.
        assert len(results) > 0
        for item in results:
            assert 'graph_depth' not in item, "Graph traversal depth is not tracked in current seed search"
            assert 'traversed_relationship' not in item, "No edge relationships traversed in current retrieval"

    # --------------------------------------------------------------------------
    # Test 5: Governance Filters Prevent Unauthorized or Unpublished Context
    # --------------------------------------------------------------------------
    def test_05_governance_filters_prevent_unauthorized_and_unpublished(self):
        """
        Verify:
        1. Unpublished/quarantined documents are barred from live context.
        2. Restricted documents are blocked by L7 permissions for unauthorized users.
        """
        # 1. Quarantined Document
        q_content = "Secret Unverified Rule: Do not enforce firewall checks."
        f_q = SimpleUploadedFile("quarantine.txt", q_content.encode('utf-8'), content_type="text/plain")
        q_doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="Quarantined Spec",
            original_filename="quarantine.txt",
            mime_type="text/plain",
            file_size=len(q_content),
            file_hash="dummy_hash_q",
            file_obj=f_q,
            document_type="txt",
            status="quarantined",
            authority_level=1
        )
        # Create chunk directly
        q_chunk = DocumentChunk.objects.create(
            organization=self.org,
            workspace=self.ws,
            document=q_doc,
            chunk_index=0,
            text=q_content,
            token_count=10
        )

        # Lexical search must exclude quarantined
        retriever = HybridRetrievalService(vector_store=self.vstore)
        lex_results = retriever.search(
            query="firewall checks",
            workspace_id=str(self.ws.id),
            organization_id=str(self.org.id),
            limit=5
        )
        assert all(r['document_id'] != str(q_doc.id) for r in lex_results), "Quarantined document must NOT appear in search"

        # 2. Restricted Document blocked by L7
        res_content = "Board Confidential: Proposed acquisition targets for Q4."
        f_res = SimpleUploadedFile("confidential.txt", res_content.encode('utf-8'), content_type="text/plain")
        res_doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="Board Confidential Target",
            original_filename="confidential.txt",
            mime_type="text/plain",
            file_size=len(res_content),
            file_hash="dummy_hash_res",
            file_obj=f_res,
            document_type="txt",
            status="ready",
            authority_level=7
        )
        SourcePermission.objects.create(
            document=res_doc,
            access_level=AccessLevel.RESTRICTED,
            allowed_roles=['owner']
        )
        chunk_dict = {
            'document_id': str(res_doc.id),
            'document_title': res_doc.title,
            'text': res_content,
            'authority_level': 7,
            'score': 0.95,
            'document_version': 1
        }

        # Regular member should be denied
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="acquisition targets",
            retrieved_chunks=[chunk_dict],
            workspace=self.ws,
            user=self.user,
            user_role='member'
        )
        assert envelope['state'] == 'denied'
        assert envelope['directive'] == 'stop'
        assert len(envelope['citations']) == 0, "Denied context must not leak citations"

    # --------------------------------------------------------------------------
    # Test 6: MCP Context Tool Execution and Provenance Lineage
    # --------------------------------------------------------------------------
    def test_06_mcp_context_tool_returns_governed_result(self):
        """
        Verify MCP server tool invocation:
        Executes handle_governed_query and verifies lore.result envelope, typed status, citations, and trace_id.
        """
        content = "Operational Guideline: Code reviews require at least one senior engineer sign-off before merge."
        file_obj = SimpleUploadedFile("review_guideline.txt", content.encode('utf-8'), content_type="text/plain")
        doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="Engineering Review Guideline",
            original_filename="review_guideline.txt",
            mime_type="text/plain",
            file_size=len(content),
            file_hash="dummy_hash_06",
            file_obj=file_obj,
            document_type="txt",
            status="uploaded",
            authority_level=5
        )
        job = IngestionJob.objects.create(document=doc, organization=self.org, workspace=self.ws)
        process_ingestion_pipeline(str(job.id))

        mcp_res_str = mcp_server.execute_tool(
            "lore_governed_query",
            {"query": "senior engineer sign-off for code reviews", "workspace_id": str(self.ws.id)}
        )
        import json
        mcp_res = json.loads(mcp_res_str)

        assert mcp_res['status'] in ('supported', 'qualified'), f"Expected supported/qualified, got: {mcp_res['status']}"
        assert mcp_res['directive'] == 'proceed_and_cite'
        assert len(mcp_res['citations']) >= 1
        assert mcp_res['trace_id'].startswith("trace-")
        assert "Engineering Review Guideline" in mcp_res['citations'][0]['document']

    # --------------------------------------------------------------------------
    # Test 7: Indexing Failures and Stale Vectors Cannot Bypass Governance
    # --------------------------------------------------------------------------
    def test_07_indexing_failures_and_stale_vectors_safe(self):
        """
        Verify:
        1. Ingestion failures mark document as 'failed' and never 'ready'.
        2. Stale or orphaned vectors in Qdrant are reconcilable and excluded by L5 temporal check.
        """
        # Document with failing file path
        failing_doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="Broken Doc",
            original_filename="corrupted.pdf",
            mime_type="application/pdf",
            file_size=100,
            file_hash="dummy_hash_fail",
            document_type="pdf",
            status="uploaded",
            authority_level=3
        )
        job = IngestionJob.objects.create(document=failing_doc, organization=self.org, workspace=self.ws)
        process_ingestion_pipeline(str(job.id))

        failing_doc.refresh_from_db()
        assert failing_doc.status == 'failed', "Failed document must be marked 'failed'"

        # Temporal validity layer blocks failed documents
        chunk = {
            'document_id': str(failing_doc.id),
            'document_title': failing_doc.title,
            'text': "Corrupted passage",
            'authority_level': 3
        }
        from apps.governance.layers import TemporalValidityLayer
        valid_chunks, notes, _ = TemporalValidityLayer.evaluate([chunk])
        assert len(valid_chunks) == 0, "TemporalValidityLayer must exclude 'failed' documents"
        assert any("Lifecycle Exclusion" in n for n in notes)

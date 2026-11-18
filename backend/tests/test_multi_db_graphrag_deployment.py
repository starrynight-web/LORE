import uuid
import pytest
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument, DocumentVersion
from apps.knowledge.models import KnowledgeItem, KnowledgeRelationship, DomainSummary, CanonicalEntity
from apps.knowledge.graph_adapters import (
    get_graph_store,
    DjangoORMGraphStore,
    KuzuGraphStore,
    Neo4jGraphStore,
    Neo4jGraphAdapter,
    KuzuGraphAdapter,
    CANONICAL_NODE_TYPES,
    CANONICAL_RELATIONSHIP_TYPES,
)
from apps.retrieval.vector_store import (
    get_vector_store,
    PGVectorStore,
    QdrantVectorStore,
    PgVectorLexicalAdapter,
)
from apps.sources.reconciliation import StoreReconciliationService


@pytest.mark.django_db
class MultiDbGraphRagDeploymentTestCase(TestCase):
    """
    Test suite for Multi-Database Enterprise Storage Parity & GraphRAG Visualizer APIs:
    - Dual-Mode Graph Store Adapter Protocol (KuzuDB ⇄ Neo4j Enterprise)
    - Dual-Mode Vector Store Adapter (Qdrant ⇄ pgvector with RRF k=60 and RBAC Stage 0)
    - Store Reconciliation & Transactional join key (rule_id) consistency
    - Graph Overview API Contract (RAPTOR Hierarchy, Canonical Entities, Subgraph Nodes/Edges)
    - Node Lineage Drilldown API Contract (from_source, supersedes, conflicts, overrides, governed_by)
    """

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Enterprise Test Corp", slug="ent-corp-test")
        self.ws = Workspace.objects.create(name="Production Space", organization=self.org)
        self.user = User.objects.create_user(username="lead_architect", password="password123")

        # Create sample SourceDocument with DocumentVersion
        self.doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="Global Cryptographic Key Policy",
            original_filename="crypto_policy_v2.pdf",
            document_code="SEC-CRYPTO-002",
            document_type="pdf",
            status="ready",
            authority_level=6,
            file_size=1024,
            file_hash=uuid.uuid4().hex,
        )
        self.doc_ver = DocumentVersion.objects.create(
            document=self.doc,
            version_number=2,
            file_hash=self.doc.file_hash,
            is_current=True,
        )

        # Create KnowledgeItem rule
        self.rule = KnowledgeItem.objects.create(
            organization=self.org,
            workspace=self.ws,
            document=self.doc,
            code="SEC-CRYPTO-002-R1",
            statement="All asymmetric master keys must reside within FIPS 140-3 Level 3 Hardware Security Modules.",
            component="KeyManagement",
            item_type="rule",
            status="stable",
            confidence=0.99,
            authority_level=6,
        )

        # Create CanonicalEntity
        self.entity = CanonicalEntity.objects.create(
            organization=self.org,
            workspace=self.ws,
            name="AWS KMS",
            canonical_name="AWS Key Management Service",
            entity_type="System",
            aliases=["KMS", "Key Management Service"],
            description="Cloud Hardware Security Module and Key Encryption Service",
            properties={"linked_rules": ["SEC-CRYPTO-002-R1"]},
        )

        # Create KnowledgeRelationship edge
        self.edge = KnowledgeRelationship.objects.create(
            organization=self.org,
            workspace=self.ws,
            source_item_id=self.rule.id,
            target_canonical_entity_id=self.entity.id,
            relationship_type="APPLIES_TO",
            confidence=0.98,
            approval_status="approved",
            provenance="deterministic_ontology",
        )

        # Create RAPTOR DomainSummary
        self.summary_l0 = DomainSummary.objects.filter(workspace=self.ws, domain_name="CRYPTOGRAPHY_STANDARDS").first()
        if not self.summary_l0:
            self.summary_l0 = DomainSummary.objects.create(
                organization=self.org,
                workspace=self.ws,
                domain_name="CRYPTOGRAPHY_STANDARDS",
                community_level=0,
                summary_text="Cryptographic standards governing encryption algorithms, key escrow, and hardware security modules.",
                token_count=120,
                entity_ids=[str(self.entity.id)],
                rule_ids=[str(self.rule.id)],
            )

    def test_neo4j_graph_adapter_protocol_and_ontology_types(self):
        """Validates that Neo4jGraphAdapter provides parity with Kuzu and implements canonical ontology types."""
        self.assertIs(Neo4jGraphAdapter, Neo4jGraphStore)
        self.assertIs(KuzuGraphAdapter, KuzuGraphStore)

        # Verify canonical ontology node types include technology, source, domainsummary
        for node_type in ["technology", "source", "domainsummary", "rule", "canonical_entity"]:
            self.assertIn(node_type, CANONICAL_NODE_TYPES)

        # Verify canonical relationship types include all enterprise invariants
        for rel_type in ["APPLIES_TO", "CONFLICTS_WITH", "SUPERSEDES", "GOVERNED_BY", "REQUIRES", "DEPENDS_ON"]:
            self.assertIn(rel_type, CANONICAL_RELATIONSHIP_TYPES)

        # Test adapter instantiation and neighborhood expansion fallback
        adapter = Neo4jGraphAdapter()
        res = adapter.adaptive_neighborhood_expansion(
            seed_nodes=[{"type": "rule", "id": str(self.rule.id)}],
            workspace_id=str(self.ws.id),
            organization_id=str(self.org.id),
            max_hops=2,
            max_nodes=10,
        )
        self.assertIn("status", res)
        self.assertEqual(res["status"], "completed")

    def test_pgvector_lexical_adapter_rrf_and_rbac_stage0(self):
        """Validates PgVectorLexicalAdapter ANN cosine similarity, RRF (k=60), and Stage 0 RBAC role filtering."""
        store = PgVectorLexicalAdapter(vector_dim=4)

        # Mock chunk payloads with allowed_roles for Stage 0 filtering
        c1_id = f"chunk-{uuid.uuid4().hex[:8]}"
        c2_id = f"chunk-{uuid.uuid4().hex[:8]}"
        vectors = [
            [0.1, 0.2, 0.3, 0.4],
            [0.9, 0.8, 0.7, 0.6]
        ]
        payloads = [
            {
                "document_id": str(self.doc.id),
                "rule_id": self.rule.code,
                "workspace_id": str(self.ws.id),
                "organization_id": str(self.org.id),
                "text": "FIPS 140-3 Hardware Security Modules are strictly required.",
                "allowed_roles": ["admin", "compliance_officer"],
                "access_level": "restricted",
            },
            {
                "document_id": str(self.doc.id),
                "rule_id": "SEC-GEN-001",
                "workspace_id": str(self.ws.id),
                "organization_id": str(self.org.id),
                "text": "General standard document for all employees.",
                "allowed_roles": ["member", "viewer", "admin"],
                "access_level": "internal",
            }
        ]

        store.upsert_chunks("test_collection", vectors, payloads, [c1_id, c2_id])

        # 1. Search with Stage 0 RBAC filter: Member should NOT see restricted chunk c1
        member_results = store.search(
            collection_name="test_collection",
            query_vector=[0.1, 0.2, 0.3, 0.4],
            filter_dict={"workspace_id": str(self.ws.id), "allowed_roles": ["member"]},
            limit=5
        )
        result_ids = [r["id"] for r in member_results]
        self.assertNotIn(c1_id, result_ids)
        self.assertIn(c2_id, result_ids)

        # 2. Search with Stage 0 RBAC filter: Admin CAN see restricted chunk c1
        admin_results = store.search(
            collection_name="test_collection",
            query_vector=[0.1, 0.2, 0.3, 0.4],
            filter_dict={"workspace_id": str(self.ws.id), "allowed_roles": ["admin"]},
            limit=5
        )
        admin_ids = [r["id"] for r in admin_results]
        self.assertIn(c1_id, admin_ids)

        # 3. Test search_hybrid with Reciprocal Rank Fusion (RRF, k=60)
        hybrid_results = store.search_hybrid(
            collection_name="test_collection",
            query_vector=[0.1, 0.2, 0.3, 0.4],
            query_text="Hardware Security Modules",
            filter_dict={"workspace_id": str(self.ws.id)},
            limit=5,
            use_rrf=True,
            rrf_k=60,
        )
        self.assertTrue(len(hybrid_results) > 0)
        self.assertIn("score", hybrid_results[0])
        self.assertTrue(hybrid_results[0]["score"] > 0)

    def test_reconcile_stores_cross_backend_consistency(self):
        """Validates that StoreReconciliationService reports active vector and graph backends and audits documents."""
        summary = StoreReconciliationService.reconcile(workspace_id=str(self.ws.id))
        self.assertIn("total_documents_checked", summary)
        self.assertIn("vector_backend", summary)
        self.assertIn("graph_backend", summary)
        self.assertIn("timestamp", summary)

    def test_graph_overview_api_contract(self):
        """Validates GET /api/v1/knowledge/graph-overview/ endpoint contract."""
        url = f"/api/v1/knowledge/graph-overview/?workspace_id={self.ws.id}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        data = res.data
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["workspace_id"], str(self.ws.id))

        # Check RAPTOR hierarchy and token bound ceiling
        self.assertIn("raptor_hierarchy", data)
        self.assertIn("domain_summaries", data)
        self.assertTrue(len(data["domain_summaries"]) > 0)
        for ds in data["domain_summaries"]:
            self.assertTrue(ds["within_token_budget"])
            self.assertLessEqual(ds["token_count"], 800)

        # Check Canonical Entities
        self.assertIn("canonical_entities", data)
        self.assertTrue(len(data["canonical_entities"]) > 0)

        # Check Subgraph Nodes and Edges
        self.assertIn("subgraph", data)
        self.assertIn("nodes", data["subgraph"])
        self.assertIn("edges", data["subgraph"])
        self.assertIn("edge_counts", data)
        self.assertIn("CONFLICTS_WITH", data["edge_counts"])
        self.assertIn("SUPERSEDES", data["edge_counts"])

    def test_node_lineage_api_contract(self):
        """Validates GET /api/v1/knowledge/node/<id>/lineage/ endpoint contract."""
        url = f"/api/v1/knowledge/node/{self.rule.id}/lineage/?workspace_id={self.ws.id}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        data = res.data
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["node_id"], str(self.rule.id))
        self.assertIn("node", data)
        self.assertEqual(data["node"]["authority_level"], 6)

        # Check provenance & lineage keys
        self.assertIn("from_source", data)
        self.assertEqual(data["from_source"]["document_code"], "SEC-CRYPTO-002")
        self.assertIn("supersedes_timeline", data)
        self.assertIn("conflicts", data)
        self.assertIn("overrides", data)
        self.assertIn("governed_by", data)
        self.assertIn("upstream_nodes", data)
        self.assertIn("downstream_nodes", data)

    def test_dual_mode_storage_factory_dispatch(self):
        """Validates factory dynamic selection for dual-mode enterprise profiles."""
        orm_store = get_graph_store("django_orm")
        kuzu_store = get_graph_store("kuzu")
        neo4j_store = get_graph_store("neo4j")

        self.assertIsInstance(orm_store, DjangoORMGraphStore)
        self.assertIsInstance(kuzu_store, KuzuGraphStore)
        self.assertIsInstance(neo4j_store, Neo4jGraphStore)

        qdrant_store = get_vector_store("qdrant")
        pg_store = get_vector_store("pgvector")

        self.assertIsInstance(qdrant_store, QdrantVectorStore)
        self.assertIsInstance(pg_store, PGVectorStore)


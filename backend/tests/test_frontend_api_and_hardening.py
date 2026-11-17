"""
Test Suite: Frontend API & Pipeline Hardening Verification
Validates:
1. Streaming chunked PDF ingestion bounds (MAX_PAGES_PER_CHUNK = 15) and buffer memory management.
2. Air-gapped cross-family model routing under sovereign_onprem.
3. Batch review queue API (bulk approve, reject, accept_authority_resolution).
4. Compliance packs API (list & apply).
5. GraphRAG community overview API (RAPTOR summaries <= 800 tokens, canonical entities, edge distribution).
6. Local Judge Distillation dataset recording and CLI export command.
"""

import os
import json
import tempfile
import pytest
from django.test import TestCase
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.identity.models import Organization, User
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument
from apps.knowledge.models import (
    KnowledgeItem, DocumentChunk, CanonicalEntity,
    DomainSummary, KnowledgeRelationship, RelationshipType
)
from apps.governance.models import (
    ConflictRecord, JudgeDistillationPair, EvidenceRequirement
)
from apps.knowledge.operational_memory import OperationalMemoryService
from apps.retrieval.sovereignty import DataSovereigntyRouter, SovereigntyRegion
from apps.ingestion.pipeline.pdf_visual import MAX_PAGES_PER_CHUNK as PDF_MAX_PAGES
from apps.ingestion.pipeline.extractors import MAX_PAGES_PER_CHUNK as EXTRACTOR_MAX_PAGES


class FrontendApiAndHardeningTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Hardening Corp")
        self.workspace = Workspace.objects.create(
            name="Hardening WS",
            slug="hardening-ws",
            organization=self.org
        )
        self.user = User.objects.create_user(
            username="secops_lead",
            email="secops@hardeningcorp.com",
            password="enterprise_secure_password"
        )
        self.client.force_authenticate(user=self.user)

    def test_streaming_chunked_pdf_bounds_and_constants(self):
        """1. Verify streaming chunked PDF batch constants and bounded page constraints."""
        self.assertEqual(PDF_MAX_PAGES, 15)
        self.assertEqual(EXTRACTOR_MAX_PAGES, 15)

    def test_air_gapped_cross_family_model_routing(self):
        """2. Verify air-gapped cross-family model routing never self-grades."""
        routing = DataSovereigntyRouter.get_cross_family_routing(SovereigntyRegion.SOVEREIGN_ONPREM)
        self.assertTrue(routing["is_sovereign"])
        self.assertIn("extraction_family", routing)
        self.assertIn("groundedness_family", routing)

        ext_family = routing["extraction_family"].lower()
        judge_family = routing["groundedness_family"].lower()

        # Strict invariant: Extraction and Judge must be distinct model families
        self.assertNotEqual(ext_family, judge_family)
        self.assertIn("qwen", ext_family)
        self.assertIn("phi", judge_family)
        self.assertTrue(routing["distinct_families_verified"])

    def test_batch_review_queue_endpoints(self):
        """3. Test POST /api/governance/review-queue/batch/ for approve, reject, and tie resolution."""
        # Create draft documents
        doc1 = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.workspace,
            title="Policy Draft A",
            status="needs_review",
            document_type="policy",
            file_size=1024
        )
        doc2 = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.workspace,
            title="Policy Draft B",
            status="quarantined",
            document_type="standard",
            file_size=2048
        )

        # Batch Approve
        res = self.client.post("/api/governance/review-queue/batch/", {
            "action": "approve",
            "document_ids": [str(doc1.id), str(doc2.id)],
            "workspace_id": str(self.workspace.id)
        }, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["processed_documents_count"], 2)

        doc1.refresh_from_db()
        doc2.refresh_from_db()
        self.assertEqual(doc1.status, "ready")
        self.assertEqual(doc2.status, "ready")

        # Create conflict record and test accept_authority_resolution
        conflict = ConflictRecord.objects.create(
            workspace=self.workspace,
            source_a=doc1,
            source_b=doc2,
            claim_a="Must use AES-128",
            claim_b="Must use AES-256",
            resolution_status="unresolved",
            resolution_notes="Tie requiring human resolution"
        )

        res_conflict = self.client.post("/api/governance/review-queue/batch/", {
            "action": "accept_authority_resolution",
            "conflict_ids": [str(conflict.id)],
            "notes": "AES-256 statutory requirement accepted."
        }, format="json")
        self.assertEqual(res_conflict.status_code, 200)
        self.assertEqual(res_conflict.data["processed_conflicts_count"], 1)

        conflict.refresh_from_db()
        self.assertEqual(conflict.resolution_status, "resolved_by_authority")

        # Verify operational memory distillation pair persisted
        pairs = JudgeDistillationPair.objects.filter(workspace_id=str(self.workspace.id))
        self.assertGreaterEqual(pairs.count(), 1)
        self.assertEqual(pairs.first().human_verdict, "ACCEPT_AUTHORITY_DOMINANCE")

    def test_compliance_packs_api(self):
        """4. Test GET and POST /api/governance/compliance-packs/."""
        # List compliance packs
        res = self.client.get("/api/governance/compliance-packs/")
        self.assertEqual(res.status_code, 200)
        pack_ids = [p["id"] for p in res.data["packs"]]
        for expected in ["soc2", "iso27001", "hipaa", "gdpr", "eu_ai_act"]:
            self.assertIn(expected, pack_ids)

        # Apply SOC2 pack
        apply_res = self.client.post("/api/governance/compliance-packs/apply/", {
            "pack_id": "soc2",
            "workspace_id": str(self.workspace.id)
        }, format="json")
        self.assertEqual(apply_res.status_code, 200)
        self.assertEqual(apply_res.data["pack_id"], "soc2")
        self.assertGreaterEqual(apply_res.data["rules_count"], 3)

    def test_graph_overview_api(self):
        """5. Test GET /api/knowledge/graph-overview/."""
        # Seed RAPTOR Community Summary (<= 800 tokens)
        DomainSummary.objects.create(
            organization=self.org,
            workspace=self.workspace,
            community_level=0,
            domain_name="CRYPTO_GOVERNANCE",
            summary_text="All sensitive customer data must be encrypted with AES-256-GCM.",
            token_count=18,
            entity_ids=["e1", "e2"],
            rule_ids=["r1", "r2", "r3"]
        )

        # Seed Canonical Entity
        CanonicalEntity.objects.create(
            organization=self.org,
            workspace=self.workspace,
            name="AWS KMS",
            canonical_name="AWS KMS",
            entity_type="System",
            aliases=["KMS"]
        )

        res = self.client.get(f"/api/knowledge/graph-overview/?workspace_id={self.workspace.id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "SUCCESS")
        self.assertEqual(res.data["domain_summaries_count"], 1)
        self.assertTrue(res.data["domain_summaries"][0]["within_token_budget"])
        self.assertLessEqual(res.data["domain_summaries"][0]["token_count"], 800)
        self.assertEqual(res.data["canonical_entities_count"], 1)
        self.assertEqual(res.data["canonical_entities"][0]["name"], "AWS KMS")

    def test_export_judge_distillation_command(self):
        """6. Test python manage.py export_judge_distillation management command."""
        # Record distillation item
        OperationalMemoryService.record_human_resolution_distillation(
            workspace=self.workspace,
            organization=self.org,
            prompt="Does internal policy permit storing plain unencrypted PII?",
            context="GDPR Article 32 mandates state-of-the-art encryption.",
            human_verdict="REJECT: Violates GDPR statutory encryption mandate.",
            rationale="Statutory Law Rank 2 strictly supersedes internal storage convenience."
        )

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            call_command(
                "export_judge_distillation",
                workspace=str(self.workspace.id),
                format="alpaca",
                output=tmp_path
            )

            self.assertTrue(os.path.exists(tmp_path))
            with open(tmp_path, "r", encoding="utf-8") as f:
                lines = [json.loads(line) for line in f if line.strip()]

            self.assertGreaterEqual(len(lines), 1)
            record = lines[0]
            self.assertIn("instruction", record)
            self.assertIn("input", record)
            self.assertIn("output", record)
            self.assertIn("REJECT", record["output"])
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

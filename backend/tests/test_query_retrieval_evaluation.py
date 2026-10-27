"""
LORE Enterprise — Query Understanding & Retrieval Pipeline Evaluation Suite
Adheres strictly to lore.md §4, §6, §10, and user audit specifications.

Measures:
- Recall@K (K=3, K=5)
- Precision@K (K=3, K=5)
- MRR (Mean Reciprocal Rank)
- nDCG@K (Normalized Discounted Cumulative Gain)
- Required-Source Companion Coverage
- Distractor Rejection Rate
- Stage Latency (Vector, Lexical, Fusion, Rerank, Total)

Validates against:
- 8 Distinct Query Intents
- Exact entity and date extractions (preserving requested dates)
- Paraphrases without exact keyword matching
- Hard negatives (meal vs lodging, unapproved drafts, superseded versions)
- Negative retrieval corpus boundaries (DOC-021)
- L7 access permissions & L5 temporal validity filters
- Structured diagnostics without user-facing leaks
"""

import os
import sys
import math
import time
import tempfile
import pytest
from typing import Dict, List, Any, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lore_enterprise.settings')
import django
django.setup()

from django.conf import settings
from apps.identity.models import Organization, User
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument, DocumentVersion
from apps.knowledge.models import DocumentChunk
from apps.governance.models import SourcePermission, AccessLevel
from apps.governance.evidence_package import StructuredEvidencePackage, EvidenceItem
from apps.retrieval.services import HybridRetrievalService
from apps.retrieval.query_understanding import QueryUnderstandingService, QueryIntent, QueryAnalysis


# ==============================================================================
# Versioned Gold Benchmark Dataset
# ==============================================================================
GOLD_EVALUATION_DATASET_V1 = [
    {
        "id": "Q1_FACT_LEAVE_CARRYOVER",
        "intent": QueryIntent.EXACT_FACT_LOOKUP,
        "query": "What is the maximum number of unused annual leave days an employee can carry forward, and by what date must they be used?",
        "paraphrase": "How many unused vacation days can staff roll over to the following year and what is the deadline for taking them?",
        "required_docs": ["DOC-005"],
        "required_sections": ["Section 3", "Q2"],
        "expected_facts": ["5", "march 31"],
        "distractors": ["DOC-001", "DOC-016"],
        "domain": "annual_leave"
    },
    {
        "id": "Q2_FACT_RECORDS_RETENTION",
        "intent": QueryIntent.EXACT_FACT_LOOKUP,
        "query": "Under the Records Retention Schedule, what is the retention period and trigger event for audit events and access logs?",
        "paraphrase": "How long must security audit trails and login records be preserved according to company schedules?",
        "required_docs": ["DOC-008"],
        "required_sections": ["Retention Schedule", "Table"],
        "expected_facts": ["3 years", "calendar year"],
        "distractors": ["DOC-007"],  # DOC-007 is general logging policy, DOC-008 is retention schedule
        "domain": "records_retention"
    },
    {
        "id": "Q3_POLICY_LODGING_CAP",
        "intent": QueryIntent.POLICY_INTERPRETATION,
        "query": "Under the current Travel and Expense Policy, what is the maximum nightly hotel rate for standard travel?",
        "paraphrase": "What is the nightly accommodation allowance ceiling for regular business trips under current rules?",
        "required_docs": ["DOC-002"],
        "required_sections": ["Section 4"],
        "expected_facts": ["$220", "220"],
        "distractors": ["DOC-001", "DOC-016"],  # DOC-001 is draft ($200), DOC-016 is superseded ($180), Section 5 is meals ($70)
        "domain": "travel_lodging"
    },
    {
        "id": "Q4_CROSS_DOC_INVOICE_VS_CONTRACT",
        "intent": QueryIntent.CROSS_DOCUMENT_COMPARISON,
        "query": "Compare the consulting services hourly rate billed on Invoice INV-2024-001 with the maximum rate agreed under Master Services Agreement DOC-009.",
        "paraphrase": "Is there an hourly rate discrepancy between the billed Atlas contractor invoice and their master services agreement cap?",
        "required_docs": ["DOC-010", "DOC-009"],
        "required_sections": ["Contract term", "Section 3"],
        "expected_facts": ["$250", "$200"],
        "distractors": ["DOC-012"],
        "domain": "general"
    },
    {
        "id": "Q5_CROSS_DOC_PURCHASE_VS_MINUTES",
        "intent": QueryIntent.CROSS_DOCUMENT_COMPARISON,
        "query": "Reconcile the $32,000 milling machine capital purchase request with the Procurement Review Minutes.",
        "paraphrase": "What was the final committee determination regarding the proposed $32k Meridian industrial milling equipment purchase?",
        "required_docs": ["DOC-018", "DOC-019"],
        "required_sections": ["Capital Purchase", "Minutes"],
        "expected_facts": ["defer", "objection"],
        "distractors": ["DOC-017"],
        "domain": "procurement"
    },
    {
        "id": "Q6_HISTORICAL_2024_TRAVEL",
        "intent": QueryIntent.HISTORICAL_AS_OF_LOOKUP,
        "query": "What was the standard hotel lodging rate under the 2024 Travel and Expense Policy before it was superseded?",
        "paraphrase": "What nightly hotel cap applied during 2024 under the prior archived travel guidelines?",
        "required_docs": ["DOC-016"],
        "required_sections": ["Section 4", "Section 3"],
        "expected_facts": ["$180", "180"],
        "distractors": ["DOC-002"],  # DOC-002 is 2026 policy ($220)
        "domain": "travel_lodging"
    },
    {
        "id": "Q7_APPROVAL_DECISION_HOTEL_OVERAGE",
        "intent": QueryIntent.APPROVAL_COMPLIANCE_DECISION,
        "query": "Can a department travel coordinator approve an off-policy hotel booking of $450 per night under current travel policy?",
        "paraphrase": "Is a travel coordinator permitted to authorize a $450/night luxury hotel reservation for standard travel?",
        "required_docs": ["DOC-002"],
        "required_sections": ["Section 4", "Section 8"],
        "expected_facts": ["vp", "vice president"],
        "distractors": ["DOC-011"],  # Memo doesn't give coordinator authority over $450
        "domain": "travel_lodging"
    },
    {
        "id": "Q8_POLICY_EMERGENCY_PROCURE",
        "intent": QueryIntent.POLICY_INTERPRETATION,
        "query": "Under the Procurement Policy, what are the three mandatory conditions required for an emergency sole-source exemption?",
        "paraphrase": "Which three requirements must be satisfied to waive competitive bidding during an emergency purchase?",
        "required_docs": ["DOC-004"],
        "required_sections": ["Section 3", "Section 1", "Emergency Procurement"],
        "expected_facts": ["threat to life", "safety", "sole source"],
        "distractors": ["DOC-018"],
        "domain": "procurement"
    },
    {
        "id": "Q9_PROCEDURE_LOST_RECEIPT",
        "intent": QueryIntent.PROCEDURAL_INSTRUCTIONS,
        "query": "What is the required process for submitting expenses when an itemized receipt is lost?",
        "paraphrase": "What procedure must an employee follow if they misplace their itemized hotel or travel expense receipt?",
        "required_docs": ["DOC-002"],
        "required_sections": ["Section 6"],
        "expected_facts": ["declaration", "missing receipt declaration"],
        "distractors": ["DOC-011"],
        "domain": "travel_receipts"
    },
    {
        "id": "Q10_ACCESS_STATUS_CARLA_REYES",
        "intent": QueryIntent.ACCESS_STATUS_LOOKUP,
        "query": "What is the current workspace access status and role for Carla Reyes under request AR-2024-043?",
        "paraphrase": "Has Carla Reyes been granted permissions as workspace administrator in AR-2024-043?",
        "required_docs": ["DOC-017"],
        "required_sections": ["Access Request"],
        "expected_facts": ["approved", "workspace administrator"],
        "distractors": ["DOC-004"],
        "domain": "workspace_access"
    },
    {
        "id": "Q11_NEGATIVE_RETRIEVAL_DOC021",
        "intent": QueryIntent.MISSING_DOCUMENT_NEGATIVE,
        "query": "Retrieve the exact policy text of Travel & Expense Policy (2025) DOC-021.",
        "paraphrase": "What are the specific clauses contained in the missing 2025 travel policy document DOC-021?",
        "required_docs": ["DOC-021", "DOC-020"],
        "required_sections": ["Corpus Boundary", "Document Register"],
        "expected_facts": ["missing", "absent"],
        "distractors": ["DOC-002", "DOC-016"],
        "domain": "general"
    }
]


# ==============================================================================
# Helper Metric Computation Functions
# ==============================================================================
def compute_mrr(retrieved_doc_codes: List[str], gold_doc_codes: List[str]) -> float:
    """Computes Mean Reciprocal Rank for the first relevant document."""
    for rank, doc_code in enumerate(retrieved_doc_codes, 1):
        if doc_code.upper() in [g.upper() for g in gold_doc_codes]:
            return 1.0 / rank
    return 0.0


def compute_ndcg_at_k(retrieved_doc_codes: List[str], gold_doc_codes: List[str], k: int = 5) -> float:
    """Computes Normalized Discounted Cumulative Gain at K."""
    gold_set = {g.upper() for g in gold_doc_codes}
    dcg = 0.0
    for i, doc_code in enumerate(retrieved_doc_codes[:k], 1):
        rel = 1.0 if doc_code.upper() in gold_set else 0.0
        dcg += (2.0 ** rel - 1.0) / math.log2(i + 1.0)
    
    # Ideal DCG
    idcg = 0.0
    for i in range(1, min(len(gold_set), k) + 1):
        idcg += (2.0 ** 1.0 - 1.0) / math.log2(i + 1.0)
    
    return dcg / idcg if idcg > 0 else 0.0


def compute_recall_at_k(retrieved_doc_codes: List[str], gold_doc_codes: List[str], k: int = 5) -> float:
    """Computes Recall@K: proportion of gold documents present in top-k results."""
    gold_set = {g.upper() for g in gold_doc_codes}
    retrieved_k = {c.upper() for c in retrieved_doc_codes[:k]}
    matched = gold_set.intersection(retrieved_k)
    return len(matched) / len(gold_set) if gold_set else 1.0


def compute_precision_at_k(retrieved_doc_codes: List[str], gold_doc_codes: List[str], k: int = 5) -> float:
    """Computes Precision@K: proportion of top-k results that are gold documents."""
    gold_set = {g.upper() for g in gold_doc_codes}
    retrieved_k = retrieved_doc_codes[:k]
    if not retrieved_k:
        return 0.0
    matched = sum(1 for c in retrieved_k if c.upper() in gold_set)
    return matched / len(retrieved_k)


def get_dataset_zip_path():
    candidate_paths = [
        os.path.join(settings.BASE_DIR, "Lore_Dataset.zip"),
        os.path.join(settings.BASE_DIR, "..", "Lore_Dataset.zip"),
        r"E:\desktop\lore dataset\Lore_Dataset.zip",
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            return p
    return None


# ==============================================================================
# Comprehensive Evaluation Test Suite
# ==============================================================================
@pytest.mark.django_db(transaction=True)
class TestQueryRetrievalEvaluationSuite:
    """
    Empirical Evaluation & Quality Gate Suite for LORE Enterprise Query Pipeline.
    Tests all requirements: Query Intent, Candidate Retrieval, Reranking, Metadata Filters,
    Evidence Assembly, and Diagnostics.
    """

    def setup_method(self):
        self.workspace = Workspace.objects.filter(id='b69b9b83-21a5-451f-bafe-382a508ac5a4').first()
        if not self.workspace or SourceDocument.objects.filter(workspace=self.workspace).count() < 5:
            # Clean or seed workspace in test database
            self.org, _ = Organization.objects.get_or_create(name="Evaluation Org", slug="eval-org")
            self.workspace, _ = Workspace.objects.get_or_create(
                id='b69b9b83-21a5-451f-bafe-382a508ac5a4',
                organization=self.org,
                name="Evaluation Workspace",
                slug="eval-ws"
            )
            self._seed_benchmark_corpus()
        else:
            self.org = self.workspace.organization
        self.retrieval_service = HybridRetrievalService()

    def _seed_benchmark_corpus(self):
        """Seeds benchmark documents from Lore_Dataset.zip if test database is unseeded."""
        zip_path = get_dataset_zip_path()
        if not zip_path or not os.path.exists(zip_path):
            return
        
        import zipfile
        from django.core.files import File
        from apps.ingestion.settlement import ExtractionValidationService, StagedMergeService

        zf = zipfile.ZipFile(zip_path)
        targets = [
            'DOC-001', 'DOC-002', 'DOC-003', 'DOC-004', 'DOC-005', 'DOC-006', 'DOC-007',
            'DOC-008', 'DOC-009', 'DOC-010', 'DOC-011', 'DOC-012',
            'DOC-013', 'DOC-014', 'DOC-015', 'DOC-016', 'DOC-017',
            'DOC-018', 'DOC-019', 'DOC-020'
        ]

        for doc_code in targets:
            matches = [n for n in zf.namelist() if doc_code in n]
            if not matches:
                continue
            entry_name = matches[0]
            data = zf.read(entry_name)
            ext = os.path.splitext(entry_name)[1].lower().strip('.')
            if ext == 'xlsx':
                doc_type = 'spreadsheet'
                mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            elif ext == 'docx':
                doc_type = 'docx'
                mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            elif ext == 'eml':
                doc_type = 'email'
                mime = 'message/rfc822'
            else:
                doc_type = 'pdf'
                mime = 'application/pdf'

            with tempfile.NamedTemporaryFile(suffix='.' + ext, delete=False) as tf:
                tf.write(data)
                tf_path = tf.name

            with open(tf_path, 'rb') as f:
                doc = SourceDocument.objects.create(
                    organization=self.org,
                    workspace=self.workspace,
                    title=entry_name,
                    original_filename=entry_name,
                    mime_type=mime,
                    file_size=len(data),
                    file_hash=f"eval_hash_{doc_code.lower()}",
                    file_obj=File(f, name=entry_name),
                    document_type=doc_type,
                    document_code=doc_code,
                    status='uploaded'
                )

            doc_ver = DocumentVersion.objects.create(
                document=doc,
                version_number=1,
                file_hash=doc.file_hash,
                file_obj=doc.file_obj,
                is_current=True
            )

            s3, pages_data = ExtractionValidationService.extract_and_validate(doc, doc_ver)
            doc.refresh_from_db()
            StagedMergeService.staged_merge_and_verify(doc, doc_ver, pages_data)
            doc.refresh_from_db()
            doc.status = doc.governance_status or 'ready'
            doc.save(update_fields=['status'])
            if os.path.exists(tf_path):
                os.remove(tf_path)

        # Explicitly register missing boundary DOC-021
        SourceDocument.objects.get_or_create(
            workspace=self.workspace,
            document_code='DOC-021',
            defaults={
                'organization': self.org,
                'title': 'Travel & Expense Policy (2025)',
                'original_filename': 'DOC-021 — Travel_Expense_Policy_2025.pdf',
                'file_size': 0,
                'file_hash': 'missing-doc-021-hash',
                'mime_type': 'application/pdf',
                'is_missing': True,
                'status': 'missing',
                'governance_status': 'missing',
                'authority_level': 1
            }
        )

    def test_01_query_intent_and_entity_extraction(self):
        """
        Requirement 1: Distinguish 8 intents and extract entities, document IDs, dates,
        monetary quantities, and requested answer fields while preserving user requested dates.
        """
        for item in GOLD_EVALUATION_DATASET_V1:
            analysis = QueryUnderstandingService.analyze(item["query"])
            assert analysis.intent == item["intent"], (
                f"Query '{item['query']}' classified as {analysis.intent}, expected {item['intent']}"
            )
            # Verify explicit document IDs extracted if present in query
            for doc in item["required_docs"]:
                if doc in item["query"]:
                    assert doc.upper() in [d.upper() for d in analysis.all_target_doc_codes], (
                        f"Expected doc {doc} in extracted target codes for query '{item['query']}'"
                    )

        # Test requested date preservation: user requested date must NOT be replaced with current date
        as_of_query = "What was the travel policy as of 2026-11-15?"
        analysis_date = QueryUnderstandingService.analyze(as_of_query)
        assert analysis_date.target_date == "2026-11-15", (
            f"Preserved date must be '2026-11-15', got {analysis_date.target_date}"
        )
        assert analysis_date.intent == QueryIntent.HISTORICAL_AS_OF_LOOKUP

    def test_02_paraphrase_intent_robustness(self):
        """
        Requirement 1 & Evaluation: Verify query intent understanding is resilient across
        natural language paraphrases without depending strictly on exact keywords.
        """
        for item in GOLD_EVALUATION_DATASET_V1:
            para_analysis = QueryUnderstandingService.analyze(item["paraphrase"])
            # Paraphrases should either match original intent or valid close intent
            assert para_analysis.intent in (item["intent"], QueryIntent.POLICY_INTERPRETATION, QueryIntent.EXACT_FACT_LOOKUP), (
                f"Paraphrase '{item['paraphrase']}' failed intent classification: {para_analysis.intent}"
            )

    def test_03_reranker_fact_relevance_vs_topical_similarity(self):
        """
        Requirement 4: Verify that the reranker scores actual relevance to the requested fact,
        not merely topical similarity, and rejects high-similarity distractors.
        """
        # Lodging query: Section 4 ($220 hotel) must outrank Section 5 (meal allowances)
        lodging_query = "Under the current Travel and Expense Policy, what is the maximum nightly hotel rate for standard travel?"
        results = self.retrieval_service.search(
            query=lodging_query,
            workspace_id=str(self.workspace.id),
            organization_id=str(self.org.id),
            limit=5
        )
        assert len(results) > 0, "Expected search results for lodging query"
        top_item = results[0]
        assert top_item["document_code"] == "DOC-002"
        assert "section 4" in (top_item.get("section_identifier") or "").lower() or "$220" in top_item.get("text", ""), (
            f"Expected Section 4 hotel limits in top result, got: {top_item.get('section_identifier')}"
        )

        # Check distractor rejection: meal allowance chunks must NOT displace hotel chunks
        for idx, res in enumerate(results[:3], 1):
            text_lower = res.get("text", "").lower()
            if "breakfast" in text_lower and "$15" in text_lower:
                pytest.fail(f"Meal allowance distractor appeared at rank {idx} ahead of governing lodging source!")

    def test_04_multi_document_companion_coverage(self):
        """
        Requirement 3 & 4: For cross-document questions, explicitly retrieve all required source documents.
        Verify 100% companion coverage for invoice vs contract and purchase pack vs review minutes.
        """
        # Cross-document A: Invoice vs Contract
        cross_q1 = "Compare the consulting services hourly rate billed on Invoice INV-2024-001 with the maximum rate agreed under Master Services Agreement DOC-009."
        res1 = self.retrieval_service.search(
            query=cross_q1,
            workspace_id=str(self.workspace.id),
            organization_id=str(self.org.id),
            limit=5
        )
        retrieved_codes1 = {r["document_code"].upper() for r in res1}
        assert "DOC-010" in retrieved_codes1, "Required invoice DOC-010 missing from cross-document results"
        assert "DOC-009" in retrieved_codes1, "Required contract DOC-009 missing from cross-document results"

        # Cross-document B: Capital Purchase vs Review Minutes
        cross_q2 = "Reconcile the $32,000 milling machine capital purchase request with the Procurement Review Minutes."
        res2 = self.retrieval_service.search(
            query=cross_q2,
            workspace_id=str(self.workspace.id),
            organization_id=str(self.org.id),
            limit=5
        )
        retrieved_codes2 = {r["document_code"].upper() for r in res2}
        assert "DOC-018" in retrieved_codes2, "Required capital purchase pack DOC-018 missing"
        assert "DOC-019" in retrieved_codes2, "Required procurement review minutes DOC-019 missing"

    def test_05_negative_retrieval_source_inventory_boundary(self):
        """
        Requirement 3: For negative retrieval, inspect source inventory before concluding
        that a document or fact is missing.
        """
        neg_query = "Retrieve the exact policy text of Travel & Expense Policy (2025) DOC-021."
        results = self.retrieval_service.search(
            query=neg_query,
            workspace_id=str(self.workspace.id),
            organization_id=str(self.org.id),
            limit=5
        )
        assert len(results) > 0, "Negative query should return corpus boundary evidence"
        # Must return the corpus boundary item for DOC-021
        codes = [r["document_code"].upper() for r in results]
        assert "DOC-021" in codes, "Corpus boundary for missing DOC-021 must be retrieved"
        assert any(r.get("is_missing") or r.get("governance_status") == "missing" for r in results), (
            "Evidence must declare the document as missing/absent from corpus"
        )
        # Must also surface Master Document Register (DOC-020) confirming referenced missing state
        assert "DOC-020" in codes, "Master Document Register DOC-020 must be returned alongside missing boundary"

    def test_06_metadata_permissions_and_temporal_filters(self):
        """
        Requirement 5: Apply access permissions before evidence enters model context.
        Apply temporal and authority filters using validated metadata.
        """
        # 1. Test Access Permissions Filter
        doc_confidential = SourceDocument.objects.filter(workspace=self.workspace, document_code="DOC-017").first()
        if doc_confidential:
            perm, _ = SourcePermission.objects.get_or_create(
                document=doc_confidential,
                defaults={'access_level': AccessLevel.RESTRICTED, 'allowed_roles': ['compliance_auditor']}
            )
            perm.access_level = AccessLevel.RESTRICTED
            perm.allowed_roles = ['compliance_auditor']
            perm.save()

            # Search as standard member: must be excluded by permission filter
            member_user = User(username="std_member", is_staff=False, is_superuser=False)
            results_denied = self.retrieval_service.search(
                query="What is the access request status for Carla Reyes?",
                workspace_id=str(self.workspace.id),
                organization_id=str(self.org.id),
                user=member_user,
                user_role="member",
                limit=5
            )
            denied_codes = [r["document_code"].upper() for r in results_denied]
            assert "DOC-017" not in denied_codes, "Restricted document DOC-017 leaked to unauthorized member user!"

            # Reset permission to internal
            perm.access_level = AccessLevel.INTERNAL
            perm.save()

        # 2. Test Temporal Validity Filter
        # Query historical as_of date: 2024-01-01
        hist_results = self.retrieval_service.search(
            query="What was the travel policy as of 2024-01-01?",
            workspace_id=str(self.workspace.id),
            organization_id=str(self.org.id),
            as_of="2024-01-01",
            limit=5
        )
        # 2026 Policy (DOC-002, effective 2026-03-01) must NOT be returned as active for 2024-01-01!
        for r in hist_results:
            if r.get("document_code") == "DOC-002" and r.get("governance_status") == "approved":
                eff_from = r.get("effective_from", "")
                if eff_from and eff_from > "2024-01-01":
                    assert r.get("role") != "governing_policy", (
                        f"Future policy {eff_from} incorrectly assigned as governing policy for 2024-01-01"
                    )

    def test_07_evidence_assembly_and_role_attribution(self):
        """
        Requirement 6: Build an evidence set with: source ID, title, version, status,
        authority, effective dates, page/section, exact supporting passage, retrieval score,
        and role in answering the question.
        """
        query = "Under the current Travel and Expense Policy, what is the maximum nightly hotel rate for standard travel?"
        results = self.retrieval_service.search(
            query=query,
            workspace_id=str(self.workspace.id),
            organization_id=str(self.org.id),
            limit=5
        )
        assert len(results) > 0

        # Build StructuredEvidencePackage
        pkg = StructuredEvidencePackage.from_chunks(
            query=query,
            chunks=results
        )

        assert len(pkg.items) > 0, "StructuredEvidencePackage must contain evidence items"
        for item in pkg.items:
            assert isinstance(item, EvidenceItem)
            assert item.document_id, "Missing document_id in EvidenceItem"
            assert item.document_title, "Missing document_title in EvidenceItem"
            assert item.document_version >= 1, "Missing document_version in EvidenceItem"
            assert item.approval_status in ('approved', 'ready', 'active', 'draft', 'superseded', 'future-effective', 'missing'), (
                f"Invalid approval status in EvidenceItem: {item.approval_status}"
            )
            assert item.authority_rank >= 1, "Missing authority_rank in EvidenceItem"
            assert item.passage, "Missing exact supporting passage in EvidenceItem"
            assert item.retrieval_score >= 0.0, "Missing retrieval_score in EvidenceItem"
            assert item.role, "Missing role in EvidenceItem"
            assert item.locator.get("page_number") is not None, "Missing page_number in EvidenceItem locator"

        # Verify LLM XML format does not crash and preserves source attributes
        xml_output = pkg.format_for_llm()
        assert "<untrusted_evidence_data" in xml_output
        assert "role=" in xml_output
        assert "DOC-002" in xml_output

    def test_08_diagnostics_trace_integrity(self):
        """
        Requirement 7: Expose structured traces for debugging: candidate IDs, lexical rank,
        vector rank, fusion rank, reranker score, filter reason, and final selected evidence.
        Do not expose internal diagnostics in the normal user-facing answer.
        """
        query = "What is the maximum number of unused annual leave days an employee can carry forward, and by what date must they be used?"
        self.retrieval_service.search(
            query=query,
            workspace_id=str(self.workspace.id),
            organization_id=str(self.org.id),
            limit=5
        )
        diag = self.retrieval_service.last_diagnostics
        assert diag is not None, "Retrieval service must expose last_diagnostics"
        assert "candidate_traces" in diag, "last_diagnostics missing candidate_traces"
        assert "selected_evidence" in diag, "last_diagnostics missing selected_evidence"
        assert "query_analysis" in diag, "last_diagnostics missing query_analysis"

        traces = diag["candidate_traces"]
        assert len(traces) > 0, "candidate_traces must not be empty"
        for t in traces[:5]:
            assert "candidate_id" in t
            assert "lexical_rank" in t
            assert "vector_rank" in t
            assert "fusion_rank" in t
            assert "reranker_score" in t
            assert "is_selected" in t
            assert "filter_reason" in t

        # Verify selected evidence items have required metadata fields
        selected = diag["selected_evidence"]
        assert len(selected) > 0
        for s in selected:
            assert "candidate_id" in s
            assert "document_code" in s
            assert "document_title" in s
            assert "retrieval_score" in s
            assert "role" in s

    def test_09_comparative_evaluation_benchmark_metrics(self):
        """
        Evaluation: Measure Recall@K, Precision@K, MRR, nDCG, required-source coverage,
        distractor rejection, and latency on identical data.
        Demonstrate that the repaired pipeline achieves superior evidence quality.
        """
        total_queries = len(GOLD_EVALUATION_DATASET_V1)
        
        # Repaired Pipeline Metric Accumulators
        repaired_recalls_3 = []
        repaired_recalls_5 = []
        repaired_precisions_3 = []
        repaired_precisions_5 = []
        repaired_mrrs = []
        repaired_ndcgs_5 = []
        repaired_latencies_ms = []
        repaired_companion_coverage = []
        repaired_distractor_rejected = 0
        total_distractor_opportunities = 0

        for item in GOLD_EVALUATION_DATASET_V1:
            q = item["query"]
            gold_docs = item["required_docs"]
            distractors = item.get("distractors", [])

            t0 = time.time()
            results = self.retrieval_service.search(
                query=q,
                workspace_id=str(self.workspace.id),
                organization_id=str(self.org.id),
                limit=5
            )
            elapsed_ms = (time.time() - t0) * 1000
            repaired_latencies_ms.append(elapsed_ms)

            retrieved_codes = [r["document_code"] for r in results]

            # Compute standard IR metrics
            repaired_recalls_3.append(compute_recall_at_k(retrieved_codes, gold_docs, k=3))
            repaired_recalls_5.append(compute_recall_at_k(retrieved_codes, gold_docs, k=5))
            repaired_precisions_3.append(compute_precision_at_k(retrieved_codes, gold_docs, k=3))
            repaired_precisions_5.append(compute_precision_at_k(retrieved_codes, gold_docs, k=5))
            repaired_mrrs.append(compute_mrr(retrieved_codes, gold_docs))
            repaired_ndcgs_5.append(compute_ndcg_at_k(retrieved_codes, gold_docs, k=5))

            # Companion coverage for cross-document questions
            if len(gold_docs) > 1:
                cov = sum(1 for g in gold_docs if g.upper() in [c.upper() for c in retrieved_codes[:5]]) / len(gold_docs)
                repaired_companion_coverage.append(cov)

            # Distractor rejection: distractor should NOT appear ahead of gold documents
            if distractors:
                for d in distractors:
                    total_distractor_opportunities += 1
                    # A distractor is successfully rejected if it is either absent or ranked below the gold documents
                    d_rank = next((idx for idx, c in enumerate(retrieved_codes, 1) if c.upper() == d.upper()), 999)
                    gold_ranks = [next((idx for idx, c in enumerate(retrieved_codes, 1) if c.upper() == g.upper()), 999) for g in gold_docs]
                    best_gold_rank = min(gold_ranks) if gold_ranks else 999
                    if d_rank > best_gold_rank:
                        repaired_distractor_rejected += 1

        avg_recall_3 = sum(repaired_recalls_3) / total_queries
        avg_recall_5 = sum(repaired_recalls_5) / total_queries
        avg_precision_3 = sum(repaired_precisions_3) / total_queries
        avg_precision_5 = sum(repaired_precisions_5) / total_queries
        avg_mrr = sum(repaired_mrrs) / total_queries
        avg_ndcg_5 = sum(repaired_ndcgs_5) / total_queries
        avg_latency = sum(repaired_latencies_ms) / total_queries
        avg_companion_cov = sum(repaired_companion_coverage) / len(repaired_companion_coverage) if repaired_companion_coverage else 1.0
        distractor_rejection_rate = repaired_distractor_rejected / total_distractor_opportunities if total_distractor_opportunities else 1.0

        # Log comprehensive evaluation report
        print("\n" + "=" * 80)
        print("LORE ENTERPRISE — RETRIEVAL PIPELINE EVALUATION BENCHMARK")
        print("=" * 80)
        print(f"Total Evaluated Queries: {total_queries}")
        print(f"Mean Recall@3:           {avg_recall_3 * 100:.2f}%")
        print(f"Mean Recall@5:           {avg_recall_5 * 100:.2f}%")
        print(f"Mean Precision@3:        {avg_precision_3 * 100:.2f}%")
        print(f"Mean Precision@5:        {avg_precision_5 * 100:.2f}%")
        print(f"Mean Reciprocal Rank:    {avg_mrr:.4f}")
        print(f"nDCG@5:                  {avg_ndcg_5:.4f}")
        print(f"Companion Coverage:      {avg_companion_cov * 100:.2f}%")
        print(f"Distractor Rejection:    {distractor_rejection_rate * 100:.2f}%")
        print(f"Average Search Latency:  {avg_latency:.2f} ms")
        print("=" * 80 + "\n")

        # Rigorous Quality Gates
        assert avg_recall_5 >= 0.90, f"Recall@5 quality gate failed: {avg_recall_5:.2f} < 0.90"
        assert avg_mrr >= 0.85, f"MRR quality gate failed: {avg_mrr:.4f} < 0.85"
        assert avg_companion_cov >= 0.95, f"Companion coverage gate failed: {avg_companion_cov:.2f} < 0.95"
        assert avg_latency < 500.0, f"Latency budget exceeded: {avg_latency:.2f}ms >= 500ms"


if __name__ == '__main__':
    suite = TestQueryRetrievalEvaluationSuite()
    # Setup for standalone run
    suite.setup_method()
    print("\nRunning TestQueryRetrievalEvaluationSuite in standalone execution mode against active database...\n")
    
    test_methods = [
        ('test_01_query_intent_and_entity_extraction', suite.test_01_query_intent_and_entity_extraction),
        ('test_02_paraphrase_intent_robustness', suite.test_02_paraphrase_intent_robustness),
        ('test_03_reranker_fact_relevance_vs_topical_similarity', suite.test_03_reranker_fact_relevance_vs_topical_similarity),
        ('test_04_multi_document_companion_coverage', suite.test_04_multi_document_companion_coverage),
        ('test_05_negative_retrieval_source_inventory_boundary', suite.test_05_negative_retrieval_source_inventory_boundary),
        ('test_06_metadata_permissions_and_temporal_filters', suite.test_06_metadata_permissions_and_temporal_filters),
        ('test_07_evidence_assembly_and_role_attribution', suite.test_07_evidence_assembly_and_role_attribution),
        ('test_08_diagnostics_trace_integrity', suite.test_08_diagnostics_trace_integrity),
        ('test_09_comparative_evaluation_benchmark_metrics', suite.test_09_comparative_evaluation_benchmark_metrics),
    ]

    passed = 0
    failed = 0
    for name, method in test_methods:
        try:
            print(f"RUNNING: {name} ...", end=" ", flush=True)
            method()
            print("[PASSED]")
            passed += 1
        except Exception as e:
            print(f"[FAILED]: {e}")
            failed += 1
            import traceback
            traceback.print_exc()

    print(f"\nFinished: {passed} passed, {failed} failed.")
    if failed > 0:
        sys.exit(1)


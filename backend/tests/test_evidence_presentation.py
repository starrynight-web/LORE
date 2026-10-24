"""
LORE Enterprise — Evidence Presentation Engine & Quality Contract Tests
Specification:
1. Prefer the shortest exact source passage that proves the answer.
2. Remove duplicate and near-duplicate passages.
3. Do not include a source merely because it was retrieved.
4. Clearly distinguish direct evidence from inference.
5. Do not invent page numbers, approval status, source passages, or effective dates.
6. If the source cannot prove a claim, state that limitation.
7. Preserve provenance and auditability.
8. Security Invariant: Evidence must never reveal documents the user is not allowed to access.
"""

import uuid
import pytest
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from apps.governance.evidence import EvidencePresentationEngine
from apps.governance.layers import EnterpriseGovernanceEngine


@pytest.fixture
def mock_workspace(db):
    from apps.identity.models import Organization
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="Evidence Test Org", slug=f"ev-org-{uuid.uuid4().hex[:6]}")
    ws = Workspace.objects.create(name="Evidence Workspace", slug=f"ev-ws-{uuid.uuid4().hex[:6]}", organization=org)
    return ws


# ==============================================================================
# 1. DUPLICATE AND NEAR-DUPLICATE EVIDENCE PRUNING TESTS
# ==============================================================================
class TestEvidenceDeduplication:
    def test_exact_and_near_duplicate_removal(self):
        """
        Requirements:
        - Remove duplicate and near-duplicate passages.
        - Prefer higher-scoring chunk representation.
        """
        doc_id = str(uuid.uuid4())
        chunk1 = {
            "document_id": doc_id,
            "document_title": "Travel Policy 2026",
            "page_number": 3,
            "score": 0.95,
            "authority_level": 6,
            "text": "The maximum dinner allowance is $75 per day. Itemized receipts are required for reimbursement."
        }
        # Exact duplicate text
        chunk2 = {
            "document_id": doc_id,
            "document_title": "Travel Policy 2026",
            "page_number": 3,
            "score": 0.82,
            "authority_level": 6,
            "text": "The maximum dinner allowance is $75 per day. Itemized receipts are required for reimbursement."
        }
        # Near-duplicate text (>75% token overlap from same document and page)
        chunk3 = {
            "document_id": doc_id,
            "document_title": "Travel Policy 2026",
            "page_number": 3,
            "score": 0.88,
            "authority_level": 6,
            "text": "The maximum dinner allowance is $75 per day. Itemized original receipts are required for reimbursement processing."
        }
        # Distinct chunk from another page/section
        chunk4 = {
            "document_id": doc_id,
            "document_title": "Travel Policy 2026",
            "page_number": 4,
            "score": 0.90,
            "authority_level": 6,
            "text": "Breakfast allowance is $25 per day for all eligible travelers."
        }

        chunks = [chunk1, chunk2, chunk3, chunk4]
        curated = EvidencePresentationEngine.curate_citations(
            query="What is the dinner and breakfast allowance?",
            answer="The dinner allowance is $75 per day and breakfast allowance is $25 per day.",
            active_chunks=chunks
        )

        # Chunks 2 and 3 should be dropped as exact and near-duplicates of chunk 1
        # Chunk 4 should be retained as it adds the breakfast allowance
        assert len(curated) == 2
        pages = [c["page_number"] for c in curated]
        assert 3 in pages
        assert 4 in pages
        # Verify the highest-scoring dinner chunk was preserved
        dinner_cit = next(c for c in curated if c["page_number"] == 3)
        assert dinner_cit["score"] == 0.95


# ==============================================================================
# 2. SHORTEST EXACT SOURCE PASSAGE EXTRACTION TESTS
# ==============================================================================
class TestShortestExactPassage:
    def test_extracts_shortest_exact_proving_passage(self):
        """
        Requirements:
        - Prefer the smallest passage that supports the answer.
        - Guaranteed to be an exact verbatim substring of the source chunk.
        - Zero hallucination of source words.
        """
        raw_text = (
            "Section 4.1 General Provisions. All employees must register their corporate travel at least two weeks in advance. "
            "The maximum reimbursable dinner allowance is $75 per calendar day. "
            "Failure to submit expense reports within 30 days will result in delayed processing. "
            "Alcoholic beverages are not eligible for reimbursement under any circumstances."
        )

        answer = "The maximum dinner allowance is $75 per day."
        query = "What is the dinner allowance?"

        shortest = EvidencePresentationEngine.extract_shortest_passage(raw_text, answer, query)

        assert "The maximum reimbursable dinner allowance is $75 per calendar day." == shortest
        # Must be exact verbatim substring of raw_text
        assert shortest in raw_text

    def test_extracts_clean_passage_for_time_bounds(self):
        raw_text = (
            "Corporate Security Mandate. Passwords must be at least 16 characters in length. "
            "Password rotation is mandatory every 90 days for all administrative accounts. "
            "Accounts that remain inactive for 45 days will be automatically suspended."
        )
        answer = "Password rotation is mandatory every 90 days."
        query = "How often must passwords be rotated?"

        shortest = EvidencePresentationEngine.extract_shortest_passage(raw_text, answer, query)
        assert shortest == "Password rotation is mandatory every 90 days for all administrative accounts."
        assert shortest in raw_text


# ==============================================================================
# 3. METADATA FIDELITY WITHOUT INVENTION TESTS
# ==============================================================================
class TestMetadataFidelity:
    def test_does_not_invent_missing_metadata(self):
        """
        Requirements:
        - Do not invent page numbers, approval status, source passages, or effective dates.
        - Missing metadata fields remain None or 'unknown'.
        """
        doc_id = str(uuid.uuid4())
        chunk = {
            "document_id": doc_id,
            "document_title": "Unpaginated Markdown Spec",
            "document_version": 1,
            # No page_number
            "page_number": None,
            # No section / heading_path
            "heading_path": None,
            # No effective_date
            "effective_date": None,
            # No explicit status
            "status": None,
            "authority_level": 3,
            "score": 0.85,
            "text": "The data retention duration is 7 years for financial ledgers."
        }

        curated = EvidencePresentationEngine.curate_citations(
            query="What is the financial ledger retention period?",
            answer="The retention duration is 7 years.",
            active_chunks=[chunk]
        )

        assert len(curated) == 1
        cit = curated[0]
        assert cit["document_id"] == doc_id
        assert cit["document_title"] == "Unpaginated Markdown Spec"
        # Must NOT invent page number
        assert cit["page_number"] is None
        # Must NOT invent section
        assert cit["section"] is None
        # Must NOT invent effective date
        assert cit["effective_date"] is None
        # Must NOT invent approved status
        assert cit["document_status"] == "unknown"


# ==============================================================================
# 4. DOCUMENT STATUS RESOLUTION TESTS
# ==============================================================================
class TestDocumentStatusResolution:
    def test_resolves_actual_stored_status(self):
        """
        Requirements:
        - Document status: approved, draft, archived, superseded, future-effective, or unknown.
        """
        ref_time = datetime(2026, 10, 24, 12, 0, 0, tzinfo=dt_timezone.utc)

        # 1. Approved
        chk_app = {"document_title": "Doc A", "status": "approved", "authority_level": 6, "score": 0.9, "text": "Rule A applies."}
        cit_app = EvidencePresentationEngine.curate_citations("query", "Rule A", [chk_app], as_of=ref_time)[0]
        assert cit_app["document_status"] == "approved"

        # 2. Draft
        chk_draft = {"document_title": "Draft Policy B", "status": "draft", "authority_level": 3, "score": 0.9, "text": "Draft Rule B applies."}
        cit_draft = EvidencePresentationEngine.curate_citations("query", "Rule B", [chk_draft], as_of=ref_time)[0]
        assert cit_draft["document_status"] == "draft"

        # 3. Future-effective
        chk_future = {
            "document_title": "Future Policy C",
            "effective_date": "2027-01-01T00:00:00Z",
            "authority_level": 6,
            "score": 0.9,
            "text": "Rule C effective next year."
        }
        cit_future = EvidencePresentationEngine.curate_citations("query", "Rule C", [chk_future], as_of=ref_time)[0]
        assert cit_future["document_status"] == "future-effective"
        assert cit_future["effective_date"] == "2027-01-01"

        # 4. Superseded
        chk_sup = {"document_title": "Old Policy D", "is_superseded": True, "authority_level": 3, "score": 0.9, "text": "Old Rule D."}
        cit_sup = EvidencePresentationEngine.curate_citations("query", "Rule D", [chk_sup], as_of=ref_time)[0]
        assert cit_sup["document_status"] == "superseded"

        # 5. Archived
        chk_arch = {"document_title": "Archived E", "status": "archived", "authority_level": 3, "score": 0.9, "text": "Rule E."}
        cit_arch = EvidencePresentationEngine.curate_citations("query", "Rule E", [chk_arch], as_of=ref_time)[0]
        assert cit_arch["document_status"] == "archived"


# ==============================================================================
# 5. EVIDENCE TYPE: DIRECT VS INFERENCE TESTS
# ==============================================================================
class TestEvidenceTypeClassification:
    def test_distinguishes_direct_from_inference(self):
        """
        Requirements:
        - Clearly distinguish direct evidence from inference.
        """
        # Direct evidence: chunk explicitly contains the numerical value or named decision
        chk_direct = {
            "document_title": "Travel Guidelines",
            "authority_level": 6,
            "score": 0.95,
            "text": "The dinner allowance is capped at $75 per day."
        }
        cit_direct = EvidencePresentationEngine.curate_citations(
            query="What is the dinner allowance?",
            answer="The dinner allowance is $75 per day.",
            active_chunks=[chk_direct]
        )[0]
        assert cit_direct["evidence_type"] == "direct"

        # Inference: evaluated from high-level constraints without the verbatim answer
        chk_infer = {
            "document_title": "Infrastructure Standards",
            "authority_level": 4,
            "score": 0.70,
            "text": "All non-production database clusters should prioritize cost optimization during off-peak hours."
        }
        cit_infer = EvidencePresentationEngine.curate_citations(
            query="Should we shut down staging databases on weekends?",
            answer="Staging databases may be shut down on weekends to optimize non-production infrastructure costs.",
            active_chunks=[chk_infer]
        )[0]
        assert cit_infer["evidence_type"] == "inference"


# ==============================================================================
# 6. SOURCE LIMITATION HANDLING TESTS
# ==============================================================================
class TestSourceLimitations:
    def test_states_limitation_when_unapproved_or_conditional(self):
        """
        Requirements:
        - If the source cannot prove a claim or has conditions, state that limitation.
        """
        # Draft document limitation
        chk_draft = {
            "document_title": "Draft Security Guidelines",
            "status": "draft",
            "authority_level": 3,
            "score": 0.85,
            "text": "Password rotation may be extended to 180 days with biometric MFA."
        }
        cit_draft = EvidencePresentationEngine.curate_citations("query", "rotation", [chk_draft])[0]
        assert cit_draft["limitation"] is not None
        assert "Non-binding" in cit_draft["limitation"]

        # Conditional reimbursement limitation
        chk_cond = {
            "document_title": "Travel Policy",
            "status": "approved",
            "authority_level": 6,
            "score": 0.95,
            "text": "The maximum dinner allowance is $75. Original receipts required for reimbursement."
        }
        cit_cond = EvidencePresentationEngine.curate_citations("query", "$75", [chk_cond])[0]
        assert cit_cond["limitation"] is not None
        assert "receipts" in cit_cond["limitation"].lower()


# ==============================================================================
# 7. EXCLUSION OF UNNECESSARY SOURCES TESTS
# ==============================================================================
class TestUnnecessarySourceExclusion:
    def test_excludes_source_merely_retrieved(self):
        """
        Requirements:
        - Do not include a source merely because it was retrieved.
        - Other sources included only if they add necessary evidence or establish a genuine conflict.
        """
        # Primary source fully answers the single question
        chk_primary = {
            "document_title": "Primary Travel Policy",
            "authority_level": 6,
            "score": 0.95,
            "text": "The maximum dinner allowance is $75 per day."
        }
        # Secondary source merely mentions travel without adding necessary evidence
        chk_unneeded = {
            "document_title": "General Employee Handbook",
            "authority_level": 3,
            "score": 0.65,
            "text": "Corporate travel should be booked through our designated agency. Always adhere to travel policy."
        }

        curated = EvidencePresentationEngine.curate_citations(
            query="What is the dinner allowance?",
            answer="The dinner allowance is $75 per day.",
            active_chunks=[chk_primary, chk_unneeded]
        )

        # Unneeded source was excluded
        assert len(curated) == 1
        assert curated[0]["document_title"] == "Primary Travel Policy"

    def test_includes_secondary_source_when_establishing_conflict(self):
        """
        Requirements:
        - Other sources included if they establish a genuine conflict.
        """
        chk_primary = {
            "document_title": "Approved Policy v2",
            "authority_level": 6,
            "score": 0.95,
            "text": "The dinner allowance is $75."
        }
        chk_conflict = {
            "document_title": "Informal Guide",
            "authority_level": 3,
            "score": 0.80,
            "text": "Dinner allowance is $50."
        }
        conflicts = [{
            "resolution": "authority_dominance",
            "authoritative_source": "Approved Policy v2",
            "informal_claim": "Informal Guide ($50 dinner)",
            "note": "Higher authority takes precedence."
        }]

        curated = EvidencePresentationEngine.curate_citations(
            query="What is the dinner allowance?",
            answer="The dinner allowance is $75 per day.",
            active_chunks=[chk_primary, chk_conflict],
            conflicts_resolved=conflicts
        )

        assert len(curated) == 2
        titles = [c["document_title"] for c in curated]
        assert "Approved Policy v2" in titles
        assert "Informal Guide" in titles


# ==============================================================================
# 8. PERMISSION CHECKS & ZERO-LEAKAGE SECURITY TESTS
# ==============================================================================
@pytest.mark.django_db
class TestEvidencePermissionPreservation:
    def test_zero_leakage_on_denied_permission(self, mock_workspace):
        """
        Security Invariant:
        Evidence must never reveal documents the user is not allowed to access.
        Under L7 permission denial, citations must be strictly empty ([]).
        """
        from apps.sources.models import SourceDocument
        from apps.governance.models import SourcePermission, AccessLevel
        from apps.governance.contract import GovernanceRequest

        doc = SourceDocument.objects.create(
            organization=mock_workspace.organization,
            workspace=mock_workspace,
            title="Top Secret M&A Plan 2026",
            original_filename="titan.pdf",
            mime_type="application/pdf",
            file_size=2048,
            file_hash="hash-titan-2026",
            status="ready",
            authority_level=7
        )

        SourcePermission.objects.create(
            document=doc,
            access_level=AccessLevel.RESTRICTED,
            allowed_roles=["owner"]
        )

        restricted_chunk = {
            "document_id": str(doc.id),
            "document_title": doc.title,
            "document_version": 1,
            "page_number": 1,
            "authority_level": 7,
            "score": 0.99,
            "text": "Project Titan acquisition price is $4.5 Billion. Strictly confidential."
        }

        req = GovernanceRequest(
            workspace=mock_workspace,
            user_role="member",
            query="What is the Titan acquisition price?",
            candidate_evidence=[restricted_chunk]
        )

        envelope = EnterpriseGovernanceEngine.evaluate(request=req)

        assert envelope["state"] == "denied"
        # Security invariant: zero citation leakage
        assert envelope["citations"] == []
        assert envelope["evidence_found"] == []
        assert "Top Secret" not in envelope["answer"]
        assert "$4.5 Billion" not in envelope["answer"]

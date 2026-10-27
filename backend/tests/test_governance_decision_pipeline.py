"""
LORE Enterprise — Governance Decision Pipeline Comprehensive Test Suite
Specification: Master User Request & lore.md v3.0

Tests against the REAL engine (EnterpriseGovernanceEngine.evaluate):
1. Decision Classification & Intent Separation:
   - Informational retrieval vs. Action authorization
   - Hotel memo with "approve" keyword (classified as policy_compliance, not vendor_approval)
   - Purchase threshold (classified as procurement_governance)
   - Vendor onboarding (vendor-specific requirements)
   - Counterexamples with overlapping keywords in different contexts
2. Typed Requirement Registry:
   - Evaluates only domain-specific typed requirements
   - Zero pollution from unrelated categories (e.g. no SOC2 on hotel bookings)
   - Missing/pending/unapproved handling
3. Authority Resolution & Ladder:
   - DOC-002 (Rank 7) outranks DOC-011 memo (Rank 1) via authority dominance
   - Draft (DOC-001) cannot override approved policy (DOC-002)
   - Historical source (DOC-016) available for historical inquiries
4. Temporal Reasoning & Effective Dates:
   - As-of date evaluation: Nov 15, 2026 travel selects DOC-002 $220 cap, not DOC-015 $240 amendment
   - Future amendment disclosure in qualified answer
   - Superseded policy answers historical inquiry
5. Conflict Differentiation:
   - Genuine equal-rank contradictions trigger 'conflicting' (Directive: ASK_USER)
   - Non-authoritative memo vs governing policy resolved by authority dominance ('qualified')
6. Evidence Sufficiency:
   - Direct support for every requested field on factual queries
   - Approvals and conditions for authorization queries
   - Multi-source comparison presence
7. Truthful Answer-State Selection:
   - Missing document boundary verification (DOC-021 text unavailable, no fabricated approvals)
   - Missing mandatory evidence yields 'insufficient'
8. Auditability & Telemetry:
   - Verification of classification, requirements applied, evidence found/missing,
     authority decisions, temporal decisions, and audit reason codes.
"""

import uuid
from datetime import datetime, timezone as dt_timezone
import pytest
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.governance.layers import (
    EnterpriseGovernanceEngine,
    DecisionIntelligenceLayer,
    EvidenceSufficiencyLayer,
    AuthorityLayer,
    TemporalValidityLayer
)
from apps.governance.requirements import RequirementRegistry, TypedRequirement
from apps.governance.contract import Verdict, Directive, EvidenceStatus, GovernanceReasonCode


@pytest.fixture
def test_workspace(db):
    org = Organization.objects.create(name="Governance Engine Org", slug=f"gov-org-{uuid.uuid4().hex[:6]}")
    ws = Workspace.objects.create(name="Governance Engine Workspace", slug=f"gov-ws-{uuid.uuid4().hex[:6]}", organization=org)
    return ws


@pytest.fixture
def standard_corpus_chunks():
    return {
        "doc_002_policy": {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-002",
            "document_title": "Travel & Expense Policy v2",
            "document_status": "approved",
            "authority_level": 7,
            "page_number": 4,
            "text": "Hotel accommodation is capped at $220 per night. Any amount exceeding this cap requires prior written approval from the department head and Finance. Itemized receipts are mandatory for all expenses of $25 or more."
        },
        "doc_011_memo": {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-011",
            "document_title": "Internal Memorandum",
            "document_status": "informational",
            "authority_level": 1,
            "page_number": 1,
            "text": "Internal memorandum proposing a $250 hotel nightly cap. This is an informational, non-authoritative planning note that does not amend approved policy."
        },
        "doc_015_amendment": {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-015",
            "document_title": "Policy Amendment (Travel)",
            "document_status": "future-effective",
            "authority_level": 7,
            "effective_date": "2027-01-01",
            "page_number": 1,
            "text": "Policy Amendment: Hotel accommodation reimbursement cap increased to $240 per night, effective January 1, 2027."
        },
        "doc_016_archived": {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-016",
            "document_title": "Archived Travel Policy 2024",
            "document_status": "superseded",
            "authority_level": 2,
            "page_number": 1,
            "text": "Archived Travel Policy 2024. Superseded by DOC-021 (Travel & Expense Policy 2025) on January 1, 2025. Historical lodging cap was USD $150 per night."
        },
        "doc_019_minutes": {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-019",
            "document_title": "Procurement Review Meeting Minutes",
            "document_status": "approved",
            "authority_level": 4,
            "page_number": 1,
            "text": "Procurement Review Meeting Minutes. $32,000 CNC vertical milling machine purchase: Committee deferred purchase authorization due to missing CFO approval and Finance objection regarding unsupported $14,000 annual savings."
        },
        "doc_004_emergency": {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-004",
            "document_title": "Emergency Procurement Exception",
            "document_status": "draft",
            "is_draft": True,
            "authority_level": 5,
            "page_number": 2,
            "text": "Three mandatory conditions must be satisfied to use the Emergency Procurement Exception: 1) Written CFO approval before the emergency purchase bypasses the normal purchase-order sequence; 2) Documented emergency describing the circumstances, urgency, business need, and why standard sequence cannot be followed; 3) Retrospective review within two business days after the emergency purchase."
        },
        "doc_009_contract": {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-009",
            "document_title": "Vendor Contract Atlas Services",
            "document_status": "draft",
            "is_draft": True,
            "authority_level": 6,
            "page_number": 1,
            "text": "Vendor Services Agreement with Atlas Services. Term starts 1 January 2027. Annual fee of $48,000 payable in quarterly installments of $12,000. Status: unapproved draft for review."
        },
        "doc_010_invoice": {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-010",
            "document_title": "Atlas Services Invoice 2026-041",
            "document_status": "received",
            "authority_level": 3,
            "page_number": 1,
            "text": "Atlas Services Invoice 2026-041 dated 15 October 2026. Services billed: $4,800.00 ($5,184.00 inclusive of tax)."
        },
        "doc_020_register": {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-020",
            "document_title": "Master Document Register",
            "document_status": "approved",
            "authority_level": 7,
            "page_number": 1,
            "text": "Master Document Register. DOC-021: Travel & Expense Policy (2025). Status: Published in external archive; full text not deposited in local corpus."
        }
    }


# ==============================================================================
# 1. CLASSIFY THE ACTUAL DECISION & INTENT SEPARATION
# ==============================================================================
@pytest.mark.django_db
class TestDecisionClassificationAndIntentSeparation:
    """
    Requirement 1:
    Separate informational retrieval from action authorization.
    A question about a hotel memo must not automatically become a vendor approval
    request merely because it contains the word 'approve'.
    """

    def test_hotel_memo_with_keyword_approve_is_not_vendor_approval(self, test_workspace, standard_corpus_chunks):
        query = "An internal memo states the hotel nightly cap is $250. Should a travel coordinator use this figure to approve a booking?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_011_memo"], standard_corpus_chunks["doc_002_policy"]],
            workspace=test_workspace
        )
        # Must be policy_compliance, NOT vendor_approval!
        assert envelope["decision_type"] == "policy_compliance"
        assert envelope["layers_breakdown"]["l1_decision_intelligence"]["decision_type"] == "policy_compliance"
        # Must NOT demand vendor SOC 2 assessment or Schedule D data residency!
        missing_reqs = [m.get("requirement") for m in envelope.get("evidence_missing", [])]
        assert "formal_security_assessment_report" not in missing_reqs
        assert "vendor_security_assessment" not in missing_reqs
        assert "executed_data_residency_addendum" not in missing_reqs

    def test_purchase_threshold_inquiry_uses_procurement_governance(self, test_workspace, standard_corpus_chunks):
        query = "What approval is required for a $4,500 purchase under the procurement thresholds?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_019_minutes"]],
            workspace=test_workspace
        )
        assert envelope["decision_type"] == "procurement_governance"
        missing_reqs = [m.get("requirement") for m in envelope.get("evidence_missing", [])]
        assert "formal_security_assessment_report" not in missing_reqs

    def test_vendor_onboarding_action_uses_vendor_approval_requirements(self, test_workspace):
        query = "Can we approve onboarding CloudBox SaaS for processing customer data?"
        vendor_chunk = {
            "document_id": str(uuid.uuid4()),
            "document_title": "CloudBox Vendor Proposal",
            "authority_level": 3,
            "status": "ready",
            "text": "CloudBox SaaS provides automated document storage. Pricing is $15/user/month."
        }
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[vendor_chunk],
            workspace=test_workspace
        )
        assert envelope["decision_type"] == "vendor_approval"
        assert envelope["state"] == Verdict.INSUFFICIENT.value
        missing_reqs = [m.get("requirement") for m in envelope.get("evidence_missing", [])]
        assert "vendor_security_assessment" in missing_reqs or "formal_security_assessment_report" in missing_reqs

    def test_keyword_counterexamples_across_distinct_decision_types(self, test_workspace):
        """
        Tests the same keywords appearing in different decision contexts:
        - 'approve' in travel expense vs vendor onboarding vs code change
        - 'contract' in informational inquiry vs reconciliation comparison
        """
        # Context A: 'approve' in travel policy
        d1 = DecisionIntelligenceLayer.classify("Who must approve a travel expense exceeding the nightly limit?")
        assert d1.decision_type == "policy_compliance"
        assert d1.query_intent in ("informational", "policy_interpretation", "exact_fact_lookup")

        # Context B: 'approve' in vendor onboarding
        d2 = DecisionIntelligenceLayer.classify("Can we approve the vendor contract for CloudBox?")
        assert d2.decision_type == "vendor_approval"
        assert d2.is_action_proposal is True

        # Context C: 'contract' in cross-document reconciliation
        d3 = DecisionIntelligenceLayer.classify("Is there any discrepancy between this invoice and the vendor contract?")
        assert d3.decision_type == "contract_compliance"
        assert d3.query_intent == "comparison"


# ==============================================================================
# 2. AUTHORITY RESOLUTION & HIERARCHY
# ==============================================================================
@pytest.mark.django_db
class TestAuthorityResolutionAndHierarchy:
    """
    Requirement 3:
    Use validated source metadata and an explicit, configurable authority hierarchy.
    An informational memo (Rank 1) must not override a governing policy (Rank 7).
    A draft must not override an approved active policy.
    """

    def test_doc002_governing_policy_dominates_doc011_informational_memo(self, test_workspace, standard_corpus_chunks):
        query = "An internal memo states the hotel nightly cap is $250. Should a travel coordinator use this figure to approve a booking?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_011_memo"], standard_corpus_chunks["doc_002_policy"]],
            workspace=test_workspace
        )
        assert envelope["state"] in (Verdict.SUPPORTED.value, Verdict.QUALIFIED.value)
        answer = envelope["answer"]
        assert "No" in answer
        assert "$220" in answer
        assert "DOC-002" in answer or "Travel & Expense Policy v2" in answer
        # Verify authority dominance was recorded
        conflicts = envelope.get("conflicts_resolved", [])
        assert any(c.get("resolution") == "authority_dominance" for c in conflicts)

    def test_draft_cannot_override_approved_policy(self, test_workspace, standard_corpus_chunks):
        draft_chunk = {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-001 — Travel Expense Policy v1 Draft",
            "document_status": "draft",
            "is_draft": True,
            "authority_level": 7,
            "text": "Proposed lodging cap: $600 per night for all domestic travel. Status: Draft for review."
        }
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the current approved lodging cap?",
            retrieved_chunks=[draft_chunk, standard_corpus_chunks["doc_002_policy"]],
            workspace=test_workspace
        )
        assert envelope["state"] in (Verdict.SUPPORTED.value, Verdict.QUALIFIED.value)
        assert "$220" in envelope["answer"]
        assert "$600" not in envelope["answer"].split(".")[0]


# ==============================================================================
# 3. TEMPORAL REASONING & EFFECTIVE BOUNDARIES
# ==============================================================================
@pytest.mark.django_db
class TestTemporalReasoningAndEffectiveBoundaries:
    """
    Requirement 4:
    Resolve the policy that applies on the date specified in the question.
    A future-effective amendment does not apply early (upcoming change disclosed).
    A historical policy can answer a historical question even if superseded today.
    """

    def test_november_2026_travel_selects_current_policy_discloses_future_amendment(self, test_workspace, standard_corpus_chunks):
        query = "What is the maximum reimbursable hotel accommodation cost per night for business travel occurring on November 15, 2026?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_002_policy"], standard_corpus_chunks["doc_015_amendment"]],
            workspace=test_workspace
        )
        assert envelope["state"] == Verdict.QUALIFIED.value
        answer = envelope["answer"]
        assert "$220" in answer
        assert "January 1, 2027" in answer or "2027" in answer
        assert "$240" in answer

    def test_travel_after_amendment_effective_date_selects_amendment(self, test_workspace, standard_corpus_chunks):
        query = "What is the maximum reimbursable hotel accommodation cost per night for business travel occurring on February 15, 2027?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_002_policy"], standard_corpus_chunks["doc_015_amendment"]],
            workspace=test_workspace
        )
        assert "$240" in envelope["answer"]

    def test_historical_question_retrieves_superseded_policy(self, test_workspace, standard_corpus_chunks):
        query = "Which document supersedes the Archived Travel Policy 2024 , and what was its lodging cap?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_016_archived"]],
            workspace=test_workspace
        )
        assert "DOC-021" in envelope["answer"]
        assert "$150" in envelope["answer"]


# ==============================================================================
# 4. CONFLICTS VS. AUTHORITY RESOLUTION
# ==============================================================================
@pytest.mark.django_db
class TestConflictResolutionAndEqualRankContradictions:
    """
    Requirement 5:
    Distinguish genuine contradictions between governing sources from differences
    between an official policy and a non-authoritative memo.
    Equal rank contradiction -> conflicting state (Directive: ask_user).
    """

    def test_genuine_contradiction_between_equal_rank_approved_policies(self, test_workspace):
        doc_a = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Global Security Policy A",
            "document_version": 1,
            "authority_level": 7,
            "status": "approved",
            "page_number": 1,
            "text": "Employees are permitted to store customer personal data on encrypted external storage media."
        }
        doc_b = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Global Security Policy B",
            "document_version": 1,
            "authority_level": 7,
            "status": "approved",
            "page_number": 1,
            "text": "Employees must not store customer personal data on encrypted external storage media. It is strictly prohibited."
        }
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Are employees allowed to store customer personal data on encrypted external storage media?",
            retrieved_chunks=[doc_a, doc_b],
            workspace=test_workspace
        )
        assert envelope["state"] == Verdict.CONFLICTING.value
        assert envelope["directive"] == Directive.ASK_USER.value
        assert "Contradictory authoritative sources detected" in envelope["answer"]


# ==============================================================================
# 5. EVIDENCE SUFFICIENCY & ANSWER-STATE SELECTION
# ==============================================================================
@pytest.mark.django_db
class TestEvidenceSufficiencyAndAnswerStates:
    """
    Requirement 6 & 7:
    For factual questions, require direct support for every requested field.
    For authorization questions, require the approvals and conditions.
    If the corpus lacks requested document, state that its content is unavailable.
    Never fabricate security assessments or approvals.
    """

    def test_q3_procurement_cnc_minutes_authorization_denied(self, test_workspace, standard_corpus_chunks):
        query = "Can the $32,000 CNC vertical milling machine purchase be authorized based on the Procurement Review Minutes ? Why or why not?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_019_minutes"]],
            workspace=test_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]
        assert "No" in first_sentence
        assert "defer" in answer.lower()
        assert "cfo approval" in answer.lower()
        assert "$14,000" in answer

    def test_q8_atlas_invoice_vs_contract_reconciliation(self, test_workspace, standard_corpus_chunks):
        query = "Review the Atlas Services Invoice 2026-041 . Is there any discrepancy between this invoice and the Vendor Contract ?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_010_invoice"], standard_corpus_chunks["doc_009_contract"]],
            workspace=test_workspace
        )
        assert envelope["state"] in (Verdict.SUPPORTED.value, Verdict.QUALIFIED.value)
        answer = envelope["answer"]
        assert "discrepanc" in answer.lower()
        assert "15 October 2026" in answer or "Date" in answer
        assert "$4,800" in answer or "$12,000" in answer
        assert "draft" in answer.lower()

    def test_q10_missing_doc021_text_truthful_unavailable(self, test_workspace, standard_corpus_chunks):
        query = "What is the exact text of the Travel & Expense Policy (2025) that replaced the 2024 policy?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_016_archived"], standard_corpus_chunks["doc_020_register"]],
            workspace=test_workspace
        )
        assert envelope["state"] in (Verdict.SUPPORTED.value, Verdict.QUALIFIED.value)
        answer = envelope["answer"]
        assert "DOC-021" in answer
        assert "not available" in answer.lower() or "not present" in answer.lower()
        # Verify no fabricated approvals or security escalations
        assert "escalation recommendation" not in answer.lower()
        assert "security team" not in answer.lower()

    def test_q11_emergency_procurement_three_conditions(self, test_workspace, standard_corpus_chunks):
        query = "What are the three mandatory conditions that must be satisfied to use the Emergency Procurement Exception?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_004_emergency"]],
            workspace=test_workspace
        )
        assert envelope["state"] in (Verdict.SUPPORTED.value, Verdict.QUALIFIED.value)
        answer = envelope["answer"]
        assert "three mandatory conditions" in answer.lower()
        assert "CFO approval" in answer
        assert "Documented emergency" in answer
        assert "Retrospective review" in answer


# ==============================================================================
# 6. AUDITABILITY & TELEMETRY VERIFICATION
# ==============================================================================
@pytest.mark.django_db
class TestAuditabilityAndTelemetry:
    """
    Requirement 8:
    Record classification, requirements applied, evidence satisfied,
    evidence missing, authority decisions, temporal decisions, and reasons for final state.
    """

    def test_audit_record_structure_completeness(self, test_workspace, standard_corpus_chunks):
        query = "What is the maximum reimbursable hotel accommodation cost per night for business travel occurring on November 15, 2026?"
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=[standard_corpus_chunks["doc_002_policy"], standard_corpus_chunks["doc_015_amendment"]],
            workspace=test_workspace
        )
        assert "decision_type" in envelope
        assert "requirements_applied" in envelope
        assert "evidence_found" in envelope
        assert "evidence_missing" in envelope
        assert "conflicts_resolved" in envelope
        assert "notes" in envelope
        assert "reason_codes" in envelope
        assert "layers_breakdown" in envelope

        lb = envelope["layers_breakdown"]
        assert "l1_decision_intelligence" in lb
        assert "l6_authority" in lb
        assert "l5_temporal" in lb
        assert "l3_sufficiency" in lb
        assert "l2_answer_state" in lb
        assert "l0_observability" in lb

        # Verify requirements_applied is documented
        reqs_applied = envelope["requirements_applied"]
        assert isinstance(reqs_applied, list)
        assert len(reqs_applied) > 0
        assert "travel_hotel_cap_compliance" in reqs_applied

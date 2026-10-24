"""
LORE Enterprise — Document Authority & Temporal-Resolution Regression Test Suite
Requirements:
1. Treat document status, authority rank, effective date, expiration date, scope, and explicit supersession as separate attributes.
2. Do not infer that a document is approved merely because it has Authority Rank 1 (or any rank).
3. A draft must not be presented as governing policy unless the user asks what the draft says. Its draft status must be disclosed.
4. Apply explicit supersession and effective dates to determine which version governs the requested date and scope.
5. Do not apply a future-effective amendment before its effective date.
6. Do not use an archived or expired policy to answer a current-policy question unless it is needed for historical context.
7. For historical questions, select the version applicable to the requested event or date.
8. Distinguish a genuine contradiction from compatible rules or passages.
9. If two genuinely conflicting applicable sources remain and precedence cannot be established, report the conflict and identify the sources.
10. Missing or uncertain approval metadata must remain unknown; do not fabricate approval.

Test Cases:
- DOC-001 draft says $180; DOC-002 effective July 1, 2026 says $220.
- DOC-015 says $240 from January 1, 2027.
- DOC-016 is an expired/superseded 2024 policy.
- A historical travel expense predates DOC-002.
- Two applicable approved sources genuinely disagree.
- A policy has no verifiable approval status.
"""

import uuid
import pytest
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument
from apps.governance.layers import (
    EnterpriseGovernanceEngine,
    TemporalValidityLayer,
    AuthorityLayer,
    PermissionLayer
)
from apps.governance.contract import Verdict, Directive, GovernanceReasonCode
from apps.governance.evidence import EvidencePresentationEngine
from apps.decisions.synthesizer import ConciseAnswerSynthesizer


@pytest.fixture
def governance_workspace(db):
    org = Organization.objects.create(name="Governance Test Org", slug=f"gov-org-{uuid.uuid4().hex[:6]}")
    ws = Workspace.objects.create(name="Governance Workspace", slug=f"gov-ws-{uuid.uuid4().hex[:6]}", organization=org)
    return ws


# ==============================================================================
# 1. REQUIREMENT 1: SEPARATE ATTRIBUTE EVALUATION
# ==============================================================================
@pytest.mark.django_db
class TestSeparateGovernanceAttributes:
    def test_separate_attributes_evaluated_independently(self, governance_workspace):
        """
        Requirement 1:
        Treat document status, authority rank, effective date, expiration date,
        scope, and explicit supersession as strictly separate attributes.
        """
        doc_id = str(uuid.uuid4())
        chunk = {
            "document_id": doc_id,
            "document_code": "POL-SEP-001",
            "document_title": "Separation Test Policy",
            "document_version": 2,
            "status": "ready",
            "authority_level": 5,
            "effective_date": "2026-01-01",
            "expiration_date": "2028-12-31",
            "scope": "travel_meals",
            "supersedes": ["POL-SEP-OLD"],
            "score": 0.95,
            "text": "Daily meal reimbursement rate is $210 for authorized travel."
        }

        eval_tuple = TemporalValidityLayer.evaluate([chunk], as_of="2026-08-01")
        valid_chunks = eval_tuple.valid_chunks
        assert len(valid_chunks) == 1
        c = valid_chunks[0]

        # Attributes must be separately preserved and attached
        assert c["document_status"] == "approved"
        assert c["authority_level"] == 5
        assert c["effective_date"].year == 2026
        assert c["expiration_date"].year == 2028
        assert c["scope"] == "travel_meals"
        assert c["supersedes"] == ["POL-SEP-OLD"]


# ==============================================================================
# 2. TEST CASE 1 & REQUIREMENT 3: DRAFT VS APPROVED GOVERNING POLICY
# ==============================================================================
@pytest.mark.django_db
class TestDraftVsApprovedPolicyResolution:
    def test_approved_doc002_governs_over_draft_doc001(self, governance_workspace):
        """
        Test Case: DOC-001 draft says $180; DOC-002 effective July 1, 2026 says $220.
        Requirement 3:
        A draft must not be presented as governing policy unless the user asks what the draft says.
        Its draft status must be disclosed.
        For current-policy query: DOC-002 governs ($220).
        """
        doc001_draft = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-001",
            "document_title": "DOC-001 Draft Expense Policy",
            "document_version": 1,
            "authority_level": 4,
            "status": "draft",
            "is_draft": True,
            "score": 0.98,
            "text": "Status: DRAFT. Daily meal allowance is $180 per day. Pending board approval."
        }
        doc002_approved = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-002",
            "document_title": "DOC-002 Travel and Expense Policy",
            "document_version": 2,
            "authority_level": 7,
            "status": "approved",
            "effective_date": "2026-07-01",
            "score": 0.92,
            "text": "Effective July 1, 2026: The approved daily meal allowance is $220 per travel day."
        }

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the daily meal allowance under current policy?",
            retrieved_chunks=[doc001_draft, doc002_approved],
            workspace=governance_workspace,
            as_of="2026-10-01",
            decision_type="general_inquiry"
        )

        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]

        # Requirement 3: DOC-002 ($220) governs! DOC-001 draft ($180) must NOT govern.
        assert "$220" in first_sentence
        assert "$180" not in first_sentence
        assert "DOC-002" in answer

        # Citations must reflect approved governing policy
        citations = envelope["citations"]
        assert len(citations) >= 1
        assert citations[0]["document_title"] == "DOC-002 Travel and Expense Policy"
        assert citations[0]["document_status"] == "approved"

    def test_user_inquiry_for_draft_discloses_draft_status(self, governance_workspace):
        """
        Requirement 3:
        If user specifically asks what the draft says, answer with draft value ($180)
        and explicitly disclose its non-binding draft status.
        """
        doc001_draft = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-001",
            "document_title": "DOC-001 Draft Expense Policy",
            "document_version": 1,
            "authority_level": 4,
            "status": "draft",
            "is_draft": True,
            "score": 0.95,
            "text": "Status: DRAFT. Daily meal allowance is $180 per day. Pending board approval."
        }

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What does the DOC-001 draft say for meal allowance?",
            retrieved_chunks=[doc001_draft],
            workspace=governance_workspace,
            decision_type="general_inquiry"
        )

        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]

        # Answers the draft question directly with $180
        assert "$180" in first_sentence
        assert "draft" in first_sentence.lower()

        # Discloses draft status and non-binding nature
        assert "unapproved draft" in answer.lower() or "non-binding" in answer.lower()


# ==============================================================================
# 3. TEST CASE 2 & REQUIREMENT 5: FUTURE-EFFECTIVE AMENDMENT
# ==============================================================================
@pytest.mark.django_db
class TestFutureEffectiveAmendmentResolution:
    def test_future_effective_doc015_not_applied_before_effective_date(self, governance_workspace):
        """
        Test Case: DOC-015 says $240 from January 1, 2027.
        Requirement 5:
        Do not apply a future-effective amendment before its effective date.
        For current query in 2026: DOC-002 ($220) governs; DOC-015 is noted as a future caveat.
        """
        doc002_current = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-002",
            "document_title": "DOC-002 Travel and Expense Policy",
            "document_version": 2,
            "authority_level": 7,
            "status": "approved",
            "effective_date": "2026-07-01",
            "score": 0.90,
            "text": "Effective July 1, 2026: Daily meal allowance is $220."
        }
        doc015_future = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-015",
            "document_title": "DOC-015 Expense Amendment 2027",
            "document_version": 1,
            "authority_level": 7,
            "status": "future-effective",
            "effective_date": "2027-01-01",
            "score": 0.96,
            "text": "Effective January 1, 2027: Daily meal allowance increases to $240 across all tiers."
        }

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the current daily meal allowance?",
            retrieved_chunks=[doc002_current, doc015_future],
            workspace=governance_workspace,
            as_of="2026-10-15",
            decision_type="general_inquiry"
        )

        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]

        # Sentence 1 must put current effective value ($220) first, not the future $240
        assert "$220" in first_sentence
        assert "$240" not in first_sentence

        # Material caveat notes future amendment taking effect Jan 1, 2027
        assert "January 1, 2027" in answer or "2027-01-01" in answer
        assert "$240" in answer
        assert "DOC-015" in answer

    def test_doc015_applies_on_and_after_effective_date(self, governance_workspace):
        """
        Requirement 4 & 5:
        When evaluated on or after January 1, 2027, DOC-015 governs.
        """
        doc002_prior = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-002",
            "document_title": "DOC-002 Travel Policy",
            "document_version": 2,
            "authority_level": 7,
            "status": "approved",
            "effective_date": "2026-07-01",
            "score": 0.90,
            "text": "Effective July 1, 2026: Daily meal allowance is $220."
        }
        doc015_future = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-015",
            "document_title": "DOC-015 Expense Amendment 2027",
            "document_version": 1,
            "authority_level": 7,
            "status": "approved",
            "effective_date": "2027-01-01",
            "supersedes": ["DOC-002"],
            "score": 0.95,
            "text": "Effective January 1, 2027: Daily meal allowance is $240."
        }

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the daily meal allowance as of 2027?",
            retrieved_chunks=[doc002_prior, doc015_future],
            workspace=governance_workspace,
            as_of="2027-02-01",
            decision_type="general_inquiry"
        )

        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]
        assert "$240" in first_sentence


# ==============================================================================
# 4. TEST CASE 3 & REQUIREMENT 6: EXPIRED / SUPERSEDED POLICY EXCLUSION
# ==============================================================================
@pytest.mark.django_db
class TestExpiredAndSupersededPolicyExclusion:
    def test_expired_superseded_doc016_excluded_from_current_policy(self, governance_workspace):
        """
        Test Case: DOC-016 is an expired/superseded 2024 policy.
        Requirement 6:
        Do not use an archived or expired policy to answer a current-policy question.
        """
        doc016_expired = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-016",
            "document_title": "DOC-016 Travel Policy 2024",
            "document_version": 1,
            "authority_level": 7,
            "status": "archived",
            "effective_date": "2024-01-01",
            "expiration_date": "2026-06-30",
            "is_superseded": True,
            "superseded_by": "DOC-002",
            "score": 0.97,
            "text": "Daily meal reimbursement rate is $150 per day."
        }
        doc002_current = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-002",
            "document_title": "DOC-002 Travel and Expense Policy",
            "document_version": 2,
            "authority_level": 7,
            "status": "approved",
            "effective_date": "2026-07-01",
            "supersedes": ["DOC-016"],
            "score": 0.90,
            "text": "Effective July 1, 2026: Approved daily meal allowance is $220. Supersedes DOC-016."
        }

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the daily meal allowance under current policy?",
            retrieved_chunks=[doc016_expired, doc002_current],
            workspace=governance_workspace,
            as_of="2026-10-01",
            decision_type="general_inquiry"
        )

        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]

        # DOC-002 ($220) governs; DOC-016 ($150) is excluded
        assert "$220" in first_sentence
        assert "$150" not in first_sentence
        assert "DOC-002" in answer


# ==============================================================================
# 5. TEST CASE 4 & REQUIREMENT 7: HISTORICAL TRAVEL EXPENSE PREDATING DOC-002
# ==============================================================================
@pytest.mark.django_db
class TestHistoricalExpensePredatingDoc002:
    def test_historical_travel_expense_predating_doc002_selects_doc016(self, governance_workspace):
        """
        Test Case: A historical travel expense predates DOC-002.
        Requirement 7:
        For historical questions, select the version applicable to the requested event or date.
        Query asks for travel meal allowance in March 2026 (predating DOC-002's July 1, 2026 effective date).
        DOC-016 governed in March 2026 ($150).
        """
        doc016_historical = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-016",
            "document_title": "DOC-016 Travel Policy 2024",
            "document_version": 1,
            "authority_level": 7,
            "status": "approved",
            "effective_date": "2024-01-01",
            "expiration_date": "2026-06-30",
            "score": 0.93,
            "text": "Daily meal reimbursement rate is $150 per day for travel within North America."
        }
        doc002_future_to_event = {
            "document_id": str(uuid.uuid4()),
            "document_code": "DOC-002",
            "document_title": "DOC-002 Travel and Expense Policy",
            "document_version": 2,
            "authority_level": 7,
            "status": "approved",
            "effective_date": "2026-07-01",
            "supersedes": ["DOC-016"],
            "score": 0.95,
            "text": "Effective July 1, 2026: Approved daily meal allowance is $220. Supersedes DOC-016."
        }

        # Query explicitly specifies historical March 2026 travel expense predating DOC-002
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What was the travel meal allowance in March 2026, predating DOC-002?",
            retrieved_chunks=[doc016_historical, doc002_future_to_event],
            workspace=governance_workspace,
            decision_type="general_inquiry"
        )

        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]

        # Requirement 7: Must select DOC-016 ($150) because it was governing in March 2026
        assert "$150" in first_sentence
        assert "DOC-016" in answer


# ==============================================================================
# 6. TEST CASE 5 & REQUIREMENTS 8 & 9: CONFLICT RESOLUTION VS COMPATIBLE RULES
# ==============================================================================
@pytest.mark.django_db
class TestGenuineContradictionResolution:
    def test_two_applicable_approved_sources_genuinely_disagree(self, governance_workspace):
        """
        Test Case: Two applicable approved sources genuinely disagree.
        Requirements 8 & 9:
        - Two approved sources of equal rank (Rank 7) genuinely conflict on the same allowance ($200 vs $250).
        - Precedence cannot be established.
        - LORE enters 'conflicting' state.
        - The conflict is reported and both sources are explicitly identified.
        - Citations list both sources for audit inspection.
        """
        source_a = {
            "document_id": str(uuid.uuid4()),
            "document_code": "CORP-POL-2026",
            "document_title": "Corporate Travel Policy 2026",
            "document_version": 1,
            "authority_level": 7,
            "status": "approved",
            "scope": "travel_meals",
            "score": 0.95,
            "text": "Daily meal allowance is $200 for all travel reimbursement."
        }
        source_b = {
            "document_id": str(uuid.uuid4()),
            "document_code": "EXEC-GUIDE-2026",
            "document_title": "Executive Travel Guidelines 2026",
            "document_version": 1,
            "authority_level": 7,
            "status": "approved",
            "scope": "travel_meals",
            "score": 0.94,
            "text": "Daily meal allowance is $250 for all travel reimbursement."
        }

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the daily meal allowance for travel reimbursement?",
            retrieved_chunks=[source_a, source_b],
            workspace=governance_workspace,
            decision_type="general_inquiry"
        )

        # Precedence cannot be established -> conflicting state
        assert envelope["state"] == Verdict.CONFLICTING.value
        assert envelope["directive"] == Directive.ASK_USER.value

        # Requirement 9: Report the conflict and identify both sources in answer
        answer = envelope["answer"]
        assert "Contradictory" in answer or "contradict" in answer.lower()
        assert "Corporate Travel Policy 2026" in answer
        assert "Executive Travel Guidelines 2026" in answer

        # Citations must include both conflicting sources
        citations = envelope["citations"]
        assert len(citations) == 2
        titles = {c["document_title"] for c in citations}
        assert "Corporate Travel Policy 2026" in titles
        assert "Executive Travel Guidelines 2026" in titles

    def test_compatible_rules_are_distinguished_from_contradictions(self, governance_workspace):
        """
        Requirement 8:
        Distinguish a genuine contradiction from compatible rules or passages.
        Source A specifies $220 allowance; Source B specifies receipt verification requirement.
        These are compatible rules and must NOT trigger a conflicting state.
        """
        source_allowance = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Travel Allowance Policy",
            "authority_level": 7,
            "status": "approved",
            "score": 0.95,
            "text": "The approved daily meal allowance is $220."
        }
        source_receipt_rule = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Expense Audit Standards",
            "authority_level": 7,
            "status": "approved",
            "score": 0.92,
            "text": "Itemized receipts are required for all meal expenses exceeding $25."
        }

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the meal allowance and are receipts required?",
            retrieved_chunks=[source_allowance, source_receipt_rule],
            workspace=governance_workspace,
            decision_type="general_inquiry"
        )

        # Must NOT be marked conflicting!
        assert envelope["state"] != Verdict.CONFLICTING.value
        assert "$220" in envelope["answer"]


# ==============================================================================
# 7. TEST CASE 6 & REQUIREMENT 2 & 10: UNVERIFIABLE APPROVAL STATUS
# ==============================================================================
@pytest.mark.django_db
class TestUnverifiableApprovalStatus:
    def test_missing_approval_metadata_remains_unknown(self, governance_workspace):
        """
        Test Case: A policy has no verifiable approval status.
        Requirement 2: Do not infer that a document is approved merely because it has Authority Rank 1.
        Requirement 10: Missing or uncertain approval metadata must remain unknown; do not fabricate approval.
        """
        doc_unverified = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Department Operations Manual",
            "authority_level": 1,  # Rank 1 informal note
            "status": "unknown",   # Missing / unknown approval status
            "score": 0.90,
            "text": "Daily meal reimbursement rate is $160 under department operational conventions."
        }

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the meal allowance under department operations?",
            retrieved_chunks=[doc_unverified],
            workspace=governance_workspace,
            decision_type="general_inquiry"
        )

        # Status must remain unknown, NOT fabricated as approved
        citations = envelope["citations"]
        assert len(citations) >= 1
        assert citations[0]["document_status"] == "unknown"
        assert "unverified" in citations[0]["explanation"].lower() or "unknown" in citations[0]["explanation"].lower()

        # Answer must disclose that approval status is unknown / unverified
        answer = envelope["answer"]
        assert "$160" in answer
        assert "unverified and unknown" in answer or "unknown" in answer.lower()


# ==============================================================================
# 8. SECURITY & PERMISSION INTEGRITY (L7 GATE)
# ==============================================================================
@pytest.mark.django_db
class TestSecurityAndPermissionPreservation:
    def test_l7_permission_gate_denies_unauthorized_temporal_versions(self, governance_workspace):
        """
        Preserve security and audit controls:
        Permission denial at L7 isolates evidence completely with zero citation leakage.
        """
        restricted_chunk = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Restricted Board Compensation Policy",
            "authority_level": 7,
            "status": "approved",
            "score": 0.99,
            "text": "Executive per diem is $500 per day."
        }

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the executive per diem?",
            retrieved_chunks=[restricted_chunk],
            workspace=governance_workspace,
            user=None,
            user_role="anonymous",  # Anonymous is blocked by L7
            decision_type="general_inquiry"
        )

        assert envelope["state"] == Verdict.DENIED.value
        assert envelope["directive"] == Directive.STOP.value
        assert len(envelope["citations"]) == 0
        assert "$500" not in envelope["answer"]

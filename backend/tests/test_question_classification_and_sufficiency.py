"""
LORE Enterprise — Question Classification, Sufficiency Checks,
Mandatory Evidence Checklists, Conflict Resolution & Answer-State Selection Tests

REQUIREMENTS:
1. Distinguish informational questions, comparisons, policy interpretation, recommendations, and action/approval requests.
2. Apply mandatory checklists only to the appropriate decision type and scope.
3. Never bypass a checklist when a real controlled action requires it.
4. Do not treat different facts as conflicting merely because they come from different documents.
5. For exact threshold boundaries, implement and test explicit inclusive/exclusive conditions from the source policy.
6. For comparisons, extract the requested attributes from each candidate and compare them using the user's stated criteria. If "best" is ambiguous, explain the trade-off or ask a concise follow-up.
7. Separate factual answerability from authorization to perform an action.
8. Make answer-state selection reflect whether the requested facts are actually supported.
9. Preserve escalation, access control, audit logging, and human review where genuinely required.

TEST SUITE COVERS:
- Procurement amounts: $4,500, $5,000, $12,000, $25,000, and $30,000
- Emergency procurement
- Annual leave
- Security access
- Policy inquiry about "without MFA" (must not be treated as a violation)
- Controlled action bypass attempt (must be blocked as a violation)
- Supplier price and delivery comparisons
"""

import re
import uuid
import pytest
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.governance.layers import (
    EnterpriseGovernanceEngine,
    DecisionIntelligenceLayer,
    EvidenceSufficiencyLayer,
    AuthorityLayer,
    AnswerStateLayer
)
from apps.governance.contract import Verdict, Directive, EvidenceStatus, GovernanceReasonCode


@pytest.fixture
def governance_workspace(db):
    org = Organization.objects.create(name="Classification Test Org", slug=f"cls-org-{uuid.uuid4().hex[:6]}")
    ws = Workspace.objects.create(name="Classification Workspace", slug=f"cls-ws-{uuid.uuid4().hex[:6]}", organization=org)
    return ws


# ==============================================================================
# 1. PROCUREMENT THRESHOLDS: $4,500, $5,000, $12,000, $25,000, $30,000
# ==============================================================================
@pytest.mark.django_db
class TestProcurementThresholdsAndBoundaryConditions:
    """
    Requirement 5:
    For exact threshold boundaries, implement and test explicit inclusive/exclusive
    conditions from the source policy.
    Requirement 2 & 7:
    Procurement threshold questions must NOT trigger vendor security assessment checklists.
    """
    @pytest.fixture
    def procurement_policy_chunks(self):
        doc_id = str(uuid.uuid4())
        return [
            {
                "document_id": doc_id,
                "document_code": "POL-PROC-001",
                "document_title": "Enterprise Procurement Policy",
                "document_version": 2,
                "authority_level": 7,
                "status": "approved",
                "page_number": 3,
                "text": (
                    "Enterprise Procurement Policy - Section 3: Expenditure Thresholds.\n"
                    "Tier 1 (Micro-Purchase): Purchases up to and including $5,000 require only Department Manager "
                    "approval without competitive bids.\n"
                    "Tier 2 (Small Procurement): Purchases greater than $5,000 and up to and including $25,000 "
                    "require at least 3 competitive quotes and Director approval.\n"
                    "Tier 3 (Major Contracts): Purchases exceeding $25,000 require a formal competitive Request for "
                    "Proposals (RFP), Legal review, and VP approval."
                )
            }
        ]

    def test_procurement_4500_micro_purchase(self, governance_workspace, procurement_policy_chunks):
        """Amount $4,500 falls strictly into Tier 1 (<$5,000)."""
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What approval is required for a $4,500 purchase?",
            retrieved_chunks=procurement_policy_chunks,
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        assert envelope["directive"] == Directive.PROCEED_AND_CITE.value
        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]
        assert "$4,500" in first_sentence
        assert "Tier 1" in first_sentence or "Micro-Purchase" in first_sentence
        assert "Manager approval" in first_sentence
        # Crucial: Must NOT require vendor security assessment report!
        assert len(envelope.get("evidence_missing", [])) == 0

    def test_procurement_5000_exact_inclusive_boundary(self, governance_workspace, procurement_policy_chunks):
        """Amount $5,000 is an exact boundary, inclusive of Tier 1 ('up to and including $5,000')."""
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What approval is required for a $5,000 purchase?",
            retrieved_chunks=procurement_policy_chunks,
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]
        assert "$5,000" in first_sentence
        assert "Tier 1" in first_sentence or "Micro-Purchase" in first_sentence
        assert "up to and including $5,000" in first_sentence
        assert "Department Manager approval" in first_sentence

    def test_procurement_12000_small_procurement(self, governance_workspace, procurement_policy_chunks):
        """Amount $12,000 falls strictly into Tier 2 ($5,000 to $25,000)."""
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What approval is required for a $12,000 purchase?",
            retrieved_chunks=procurement_policy_chunks,
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]
        assert "$12,000" in first_sentence
        assert "Tier 2" in first_sentence or "Small Procurement" in first_sentence
        assert "Director approval" in first_sentence
        assert "3 competitive quotes" in first_sentence

    def test_procurement_25000_exact_inclusive_boundary(self, governance_workspace, procurement_policy_chunks):
        """Amount $25,000 is an exact boundary, inclusive of Tier 2 ('up to and including $25,000')."""
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What approval is required for a $25,000 purchase?",
            retrieved_chunks=procurement_policy_chunks,
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]
        assert "$25,000" in first_sentence
        assert "Tier 2" in first_sentence or "Small Procurement" in first_sentence
        assert "Director approval" in first_sentence

    def test_procurement_30000_major_contract(self, governance_workspace, procurement_policy_chunks):
        """Amount $30,000 exceeds $25,000, falling into Tier 3 (Major Contracts: RFP & VP approval)."""
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What approval is required for a $30,000 purchase?",
            retrieved_chunks=procurement_policy_chunks,
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]
        assert "$30,000" in first_sentence
        assert "Tier 3" in first_sentence or "Major Contracts" in first_sentence
        assert "RFP" in first_sentence or "Request for Proposals" in first_sentence
        assert "VP approval" in first_sentence


# ==============================================================================
# 2. EMERGENCY PROCUREMENT
# ==============================================================================
@pytest.mark.django_db
class TestEmergencyProcurement:
    def test_emergency_procurement_rules_and_retroactive_audit(self, governance_workspace):
        emergency_chunk = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Emergency Procurement Protocol",
            "authority_level": 7,
            "status": "approved",
            "page_number": 1,
            "text": (
                "Emergency Procurement Protocol: In the event of a declared system outage or critical emergency, "
                "emergency procurement allows immediate purchase without prior competitive bids, provided that "
                "retroactive justification and audit documentation are submitted within 5 business days."
            )
        }
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the policy for emergency procurement during an outage?",
            retrieved_chunks=[emergency_chunk],
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]
        assert "Emergency procurement" in first_sentence
        assert "without prior competitive bids" in first_sentence
        assert "5 business days" in first_sentence


# ==============================================================================
# 3. ANNUAL LEAVE & SECURITY ACCESS INQUIRIES
# ==============================================================================
@pytest.mark.django_db
class TestAnnualLeaveAndSecurityAccess:
    def test_annual_leave_allowance_inquiry_supported(self, governance_workspace):
        leave_chunk = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Employee Benefits Policy",
            "authority_level": 7,
            "status": "approved",
            "page_number": 4,
            "text": "Full-time employees receive 20 days of paid annual leave per calendar year, with up to 5 unused days roll-over into the next year."
        }
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the annual leave allowance?",
            retrieved_chunks=[leave_chunk],
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        assert "20 days" in answer
        assert "5 unused days" in answer

    def test_security_access_levels_inquiry_supported(self, governance_workspace):
        sec_chunk = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Identity and Access Management Policy",
            "authority_level": 7,
            "status": "approved",
            "page_number": 2,
            "text": "Security access is structured into four levels: Level 1 (Public/Guest), Level 2 (Standard Employee), Level 3 (Manager/Confidential), and Level 4 (Administrative/MFA Required)."
        }
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What are the security access levels?",
            retrieved_chunks=[sec_chunk],
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        assert "four levels" in answer
        assert "Level 1" in answer
        assert "Level 4" in answer


# ==============================================================================
# 4. POLICY INQUIRY VS ATTEMPTED ACTION VIOLATION (MFA BYPASS)
# ==============================================================================
@pytest.mark.django_db
class TestPolicyInquiryVsActionViolation:
    @pytest.fixture
    def mfa_policy_chunk(self):
        return {
            "document_id": str(uuid.uuid4()),
            "document_title": "Security Access Policy",
            "authority_level": 7,
            "status": "approved",
            "page_number": 1,
            "text": "Deploying to production or accessing administrative systems without MFA is strictly prohibited under the Security Access Policy."
        }

    def test_inquiry_asking_what_policy_says_is_not_violation(self, governance_workspace, mfa_policy_chunk):
        """
        Known Failure Pattern: A question asking what a policy says is treated as an attempted action or violation.
        Requirement 1 & 7: Separate factual answerability from authorization to perform an action.
        """
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What does the security policy say about deploying without MFA?",
            retrieved_chunks=[mfa_policy_chunk],
            workspace=governance_workspace
        )
        # Must NOT be marked violation!
        assert envelope["state"] != Verdict.VIOLATION.value
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        assert "strictly prohibited" in answer.lower()
        assert "without mfa" in answer.lower()

    def test_actual_action_attempting_bypass_is_flagged_violation(self, governance_workspace, mfa_policy_chunk):
        """
        Requirement 3: Never bypass a checklist when a real controlled action requires it.
        An explicit action request attempting to deploy without MFA must be blocked as a violation.
        """
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Deploy build 452 to production without MFA",
            retrieved_chunks=[mfa_policy_chunk],
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.VIOLATION.value
        assert envelope["directive"] == Directive.STOP.value
        assert GovernanceReasonCode.L2_RULE_VIOLATION_TRIGGERED.value in envelope["reason_codes"]


# ==============================================================================
# 5. SUPPLIER PRICE AND DELIVERY COMPARISONS
# ==============================================================================
@pytest.mark.django_db
class TestSupplierPriceAndDeliveryComparisons:
    @pytest.fixture
    def supplier_chunks(self):
        return [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Supplier Alpha Proposal",
                "authority_level": 6,
                "status": "approved",
                "page_number": 1,
                "text": "Supplier Alpha offers cloud storage at $10,000 per year with a 5 business days delivery time."
            },
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Supplier Beta Proposal",
                "authority_level": 6,
                "status": "approved",
                "page_number": 1,
                "text": "Supplier Beta offers cloud storage at $12,000 per year with a 2 business days delivery time."
            }
        ]

    def test_supplier_price_and_delivery_comparison(self, governance_workspace, supplier_chunks):
        """
        Requirement 6: Extract requested attributes from each candidate and compare them.
        """
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Compare Supplier Alpha and Supplier Beta on price and delivery time.",
            retrieved_chunks=supplier_chunks,
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        first_sentence = answer.split(". ")[0]
        # Must compare price ($10,000 vs $12,000) and delivery (5 days vs 2 days)
        assert "$10,000" in first_sentence
        assert "$12,000" in first_sentence
        assert "Supplier Alpha" in first_sentence
        assert "Supplier Beta" in first_sentence

    def test_supplier_ambiguous_best_explains_tradeoff(self, governance_workspace, supplier_chunks):
        """
        Requirement 6: If "best" is ambiguous, explain the trade-off or ask a concise follow-up.
        """
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Which supplier is best between Supplier Alpha and Supplier Beta?",
            retrieved_chunks=supplier_chunks,
            workspace=governance_workspace
        )
        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]
        # Explains trade-off: Alpha is best for cost, Beta is best for speed
        assert "cost" in answer.lower() or "price" in answer.lower()
        assert "speed" in answer.lower() or "delivery" in answer.lower()
        assert "priority" in answer.lower() or "trade-off" in answer.lower() or "best for" in answer.lower()


# ==============================================================================
# 6. COMPATIBLE PASSAGES DO NOT CONFLICT
# ==============================================================================
@pytest.mark.django_db
class TestCompatiblePassagesAvoidFalseConflicts:
    def test_distinct_procurement_tiers_do_not_conflict(self, governance_workspace):
        """
        Requirement 4: Do not treat different facts as conflicting merely because they come from different documents.
        Document A specifies Tier 1 ($5,000); Document B specifies Tier 2 ($25,000). These are complementary tiers.
        """
        chunk_t1 = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Micro-Purchase Procedure",
            "authority_level": 7,
            "status": "approved",
            "text": "Micro-purchases up to $5,000 require Department Manager approval without competitive bids."
        }
        chunk_t2 = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Small Procurement Guidelines",
            "authority_level": 7,
            "status": "approved",
            "text": "Small procurements between $5,000 and $25,000 require 3 competitive quotes and Director approval."
        }
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What are the procurement tiers?",
            retrieved_chunks=[chunk_t1, chunk_t2],
            workspace=governance_workspace
        )
        # Must NOT be marked conflicting!
        assert envelope["state"] != Verdict.CONFLICTING.value
        assert envelope["state"] == Verdict.SUPPORTED.value

    def test_distinct_supplier_proposals_do_not_conflict(self, governance_workspace):
        """Supplier Alpha at $10,000 and Supplier Beta at $12,000 are distinct commercial offers."""
        chunk_a = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Supplier Alpha Quote",
            "authority_level": 6,
            "status": "approved",
            "text": "Supplier Alpha quotes $10,000 for hardware delivery."
        }
        chunk_b = {
            "document_id": str(uuid.uuid4()),
            "document_title": "Supplier Beta Quote",
            "authority_level": 6,
            "status": "approved",
            "text": "Supplier Beta quotes $12,000 for hardware delivery."
        }
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Compare quotes from Supplier Alpha and Supplier Beta",
            retrieved_chunks=[chunk_a, chunk_b],
            workspace=governance_workspace
        )
        assert envelope["state"] != Verdict.CONFLICTING.value
        assert envelope["state"] == Verdict.SUPPORTED.value

"""
LORE Enterprise — Regression Test Suite for all 12 ans.md Defects
Covers the 10 Answering Rules:
1. Answer First (direct answer in first sentence)
2. Human Language (no robotic "authoritative operational rule" boilerplate)
3. Answer Every Requested Part (individual required-fact verification; missing fact prevents SUPPORTED)
4. Multi-Document Synthesis (explicit relations and transparent arithmetic)
5. Temporal & Authority Caveats (draft vs approved, current vs future-effective, historical vs active)
6. Negative Retrieval (truthful acknowledgment when referenced doc text is missing)
7. Citations (grounded citations attached to supported claims, deduplicated)
8. Conciseness (1-4 short sentences, no unrelated employee/table dumping)
9. Strict Separation (no internal diagnostics or trace IDs in default answer)
10. Validation (deterministic checks for dates, amounts, source status, and required fields)
"""

import uuid
import re
import pytest
from apps.governance.layers import EnterpriseGovernanceEngine
from apps.governance.contract import Verdict, Directive, GovernanceReasonCode, EvidenceStatus
from apps.decisions.synthesizer import ConciseAnswerSynthesizer, AnswerCompletenessValidator
from apps.governance.validation import AnswerQualityValidator


@pytest.fixture
def mock_workspace(db):
    from apps.identity.models import Organization
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AnsMd Test Org", slug=f"ansmd-org-{uuid.uuid4().hex[:6]}")
    ws = Workspace.objects.create(name="AnsMd Workspace", slug=f"ansmd-ws-{uuid.uuid4().hex[:6]}", organization=org)
    return ws


@pytest.fixture
def corpus_chunks():
    return {
        "doc_002_hotel": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-002 — Travel_Expense_Policy_v2.pdf",
            "document_status": "approved",
            "authority_level": 7,
            "page_number": 4,
            "score": 0.95,
            "text": "Hotel accommodation is capped at $220 per night. Any amount exceeding this cap requires prior written approval from the department head and Finance. Itemized receipts are mandatory for all expenses of $25 or more."
        },
        "doc_002_lost_receipt": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-002 — Travel_Expense_Policy_v2.pdf",
            "document_status": "approved",
            "authority_level": 7,
            "page_number": 6,
            "score": 0.92,
            "text": "Itemized receipts are mandatory for any individual expense of $25 or more. If an employee loses a receipt, an expense claim must be submitted within 15 calendar days after the trip ends accompanied by a written explanation and manager approval; reimbursement is not guaranteed."
        },
        "doc_004_emergency": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-004 — Emergency_Procurement_Exception.pdf",
            "document_status": "draft",
            "is_draft": True,
            "authority_level": 5,
            "page_number": 2,
            "score": 0.94,
            "text": "Three mandatory conditions must be satisfied to use the Emergency Procurement Exception: 1) Written CFO approval before the emergency purchase bypasses the normal purchase-order sequence; 2) Documented emergency describing the circumstances, urgency, business need, and why standard sequence cannot be followed; 3) Retrospective review within two business days after the emergency purchase."
        },
        "doc_005_leave": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-005 — Annual_Leave_Policy.pdf",
            "document_status": "draft",
            "is_draft": True,
            "authority_level": 5,
            "page_number": 3,
            "score": 0.96,
            "text": "An eligible employee may carry forward up to 5 unused working days of annual leave into the next leave year, and they expire on March 31 of that next leave year. Carryover beyond 5 days is not permitted without a written exception approved by the Head of People Operations."
        },
        "doc_008_retention": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-008 — Records_Retention_Schedule.xlsx",
            "document_status": "draft",
            "is_draft": True,
            "authority_level": 4,
            "page_number": 1,
            "score": 0.95,
            "text": "Audit events (security logs, access events, administrative activity, and audit trails) must be retained for 2 years, with the retention trigger being the event timestamp. Deletion must be suspended for events relevant to a legal hold or investigation."
        },
        "doc_009_contract": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-009 — Vendor_Contract_Atlas_Services.pdf",
            "document_status": "draft",
            "is_draft": True,
            "authority_level": 6,
            "page_number": 1,
            "score": 0.91,
            "text": "Vendor Services Agreement with Atlas Services. Term starts 1 January 2027. Annual fee of $48,000 payable in quarterly installments of $12,000. Status: unapproved draft for review."
        },
        "doc_010_invoice": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-010 — Atlas_Invoice_2026_041.pdf",
            "document_status": "received",
            "authority_level": 3,
            "page_number": 1,
            "score": 0.93,
            "text": "Atlas Services Invoice 2026-041 dated 15 October 2026. Services billed: $4,800.00 ($5,184.00 inclusive of tax)."
        },
        "doc_011_memo": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-011 — Travel_Team_Internal_Memo.pdf",
            "document_status": "informational",
            "authority_level": 1,
            "page_number": 1,
            "score": 0.89,
            "text": "Internal memorandum proposing a $250 hotel nightly cap. This is an informational, non-authoritative planning note that does not amend approved policy."
        },
        "doc_015_amendment": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-015 — Travel_Policy_Amendment_Future.pdf",
            "document_status": "future-effective",
            "is_future_effective": True,
            "authority_level": 6,
            "page_number": 1,
            "score": 0.92,
            "text": "Policy Amendment to Travel Policy. Increases hotel accommodation reimbursement cap to $240 per night. Effective date: January 1, 2027. Current policy remains in force through December 31, 2026."
        },
        "doc_016_archived": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-016 — Archived_Travel_Policy_2024.pdf",
            "document_status": "superseded",
            "authority_level": 2,
            "page_number": 1,
            "score": 0.88,
            "text": "Archived 2024 Travel Policy. Lodging cap: USD $150 per night. Superseded by DOC-021 on January 1, 2025."
        },
        "doc_017_access": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-017 — Workspace_Access_Request_Register.xlsx",
            "document_status": "active",
            "authority_level": 5,
            "page_number": 1,
            "score": 0.94,
            "text": "AR-2024-041 Alice Morgan | Workspace Editor | APPROVED | Effective 2024-10-17\nAR-2024-042 Ben Carter | Read-only Analyst | APPROVED | Effective 2024-10-21\nAR-2024-043 Carla Reyes | Workspace Administrator | Identity & Access Governance and Product Engineering | PENDING No approval recorded | Not effective"
        },
        "doc_019_minutes": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-019 — Procurement_Review_Meeting_Minutes.pdf",
            "document_status": "draft",
            "authority_level": 4,
            "page_number": 1,
            "score": 0.93,
            "text": "Procurement Review Meeting Minutes. Proposed $32,000 CNC vertical milling machine purchase. Committee Decision: Defer purchase authorization. CFO approval is missing, and Finance's objection regarding the unsupported $14,000 savings estimate and unconfirmed total delivered cost remains unresolved. Purchases exceeding $25,000 require CFO approval."
        },
        "doc_020_register": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-020 — Master_Document_Register.xlsx",
            "document_status": "active",
            "authority_level": 5,
            "page_number": 1,
            "score": 0.90,
            "text": "Master Document Register. DOC-016 Archived Travel Policy 2024 was superseded on January 1, 2025 by DOC-021 (Travel & Expense Policy 2025). Full text of DOC-021 not supplied in active knowledge base."
        }
    }


# ==============================================================================
# DEFECT REGRESSION TESTS: DEFECTS 1 TO 12
# ==============================================================================

@pytest.mark.django_db
class TestAnsMdDefectsRegression:

    def test_defect_1_annual_leave_carryover_quantity_and_expiry(self, mock_workspace, corpus_chunks):
        """
        Defect 1 (Q1):
        - Old bug: Answered with '20 days allowance' and cited DOC-008.
        - Fix: Direct answer must state '5 unused working days' and 'March 31'; cite DOC-005, not DOC-008;
          eliminate robotic phrase 'authoritative operational rule'.
        """
        chunks = [corpus_chunks["doc_005_leave"], corpus_chunks["doc_008_retention"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the maximum number of unused annual leave days an employee can carry forward, and when do they expire?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="policy_compliance"
        )
        ans = envelope["answer"]

        # Rule 1: Answer first
        first_sent = ans.split(". ")[0]
        assert "5" in first_sent
        assert "march 31" in ans.lower()

        # Rule 2: No robotic boilerplate
        assert "authoritative operational rule" not in ans.lower()

        # Rule 7: Citation accuracy
        cit_titles = [c["document_title"] for c in envelope["citations"]]
        assert any("DOC-005" in t or "Annual_Leave_Policy" in t or "Annual Leave Policy" in t for t in cit_titles)
        assert not any("DOC-008" in t for t in cit_titles)

        # Citation deduplication (Rule 7 & 8)
        assert len(envelope["citations"]) <= 2

    def test_defect_2_audit_event_retention_duration_and_trigger(self, mock_workspace, corpus_chunks):
        """
        Defect 2 (Q2):
        - Old bug: Dumped logging event list from DOC-007, missed retention duration (2 years) and trigger (event timestamp).
        - Fix: Direct answer states 2 years and event timestamp; cites DOC-008; does not dump DOC-007 list.
        """
        chunks = [corpus_chunks["doc_008_retention"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="According to the Records Retention Schedule, how long must 'Audit events' (security logs, access events) be retained, and what is the trigger?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="data_processing"
        )
        ans = envelope["answer"]

        first_sent = ans.split(". ")[0]
        assert "2 years" in first_sent.lower()
        assert "event timestamp" in first_sent.lower() or "event timestamp" in ans.lower()
        assert "authoritative operational rule" not in ans.lower()

    def test_defect_3_procurement_cnc_minutes_deferral_reasons(self, mock_workspace, corpus_chunks):
        """
        Defect 3 (Q3):
        - Old bug: Hallucinated 'Tier 3 Major Contracts', RFP, and VP approval.
        - Fix: Direct answer states purchase cannot be authorized; notes committee deferred authorization;
          cites missing CFO approval and unresolved Finance objection ($14,000 savings estimate); cites DOC-019.
        """
        chunks = [corpus_chunks["doc_019_minutes"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Can the $32,000 CNC vertical milling machine purchase be authorized based on the Procurement Review Minutes ? Why or why not?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="procurement_governance"
        )
        ans = envelope["answer"]

        first_sent = ans.split(". ")[0]
        assert any(w in first_sent.lower() for w in ["no", "cannot be authorized", "not authorized"])
        assert "cfo" in ans.lower()
        assert "14,000" in ans or "finance" in ans.lower()
        assert "tier 3" not in ans.lower()
        assert "authoritative operational rule" not in ans.lower()

    def test_defect_4_hotel_450_two_nights_arithmetic_and_exception(self, mock_workspace, corpus_chunks):
        """
        Defect 4 (Q4):
        - Old bug: Dumped 14-day advance booking timeline rule.
        - Fix: Direct answer states non-compliant; shows arithmetic ($450/2 = $225/night vs $220 cap);
          manager approval alone is insufficient; requires Finance written exception.
        """
        chunks = [corpus_chunks["doc_002_hotel"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="An employee submits an expense claim for a $450 hotel stay for 2 nights in August 2026. They have manager approval but no written exception from Finance. Is this compliant?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="policy_compliance"
        )
        ans = envelope["answer"]

        first_sent = ans.split(". ")[0]
        assert any(w in first_sent.lower() for w in ["no", "not compliant", "non-compliant"])
        assert "$225" in ans
        assert "$220" in ans
        assert "finance" in ans.lower()
        assert "14 calendar days" not in ans.lower()
        assert "authoritative operational rule" not in ans.lower()

    def test_defect_5_nov_2026_hotel_cap_vs_future_amendment(self, mock_workspace, corpus_chunks):
        """
        Defect 5 (Q5):
        - Old bug: Confused $70 meal allowance with hotel cap, dismissed amendment as draft.
        - Fix: Direct answer gives $220/night under DOC-002; explains DOC-015 specifies $240 but
          takes effect January 1, 2027, so current $220 cap governs November 2026 travel.
        """
        chunks = [corpus_chunks["doc_002_hotel"], corpus_chunks["doc_015_amendment"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the maximum reimbursable hotel accommodation cost per night for business travel occurring on November 15, 2026?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="policy_compliance"
        )
        ans = envelope["answer"]

        first_sent = ans.split(". ")[0]
        assert "$220" in first_sent
        assert "$70" not in ans
        assert "2027" in ans or "january 1" in ans.lower()
        assert "authoritative operational rule" not in ans.lower()

    def test_defect_6_superseded_archived_policy_both_parts_answered(self, mock_workspace, corpus_chunks):
        """
        Defect 6 (Q6):
        - Old bug: Found $150 cap but omitted naming superseding document DOC-021.
        - Fix: Answers BOTH parts in direct answer: superseded by DOC-021 (Travel & Expense Policy 2025),
          and lodging cap was USD $150 per night.
        """
        chunks = [corpus_chunks["doc_016_archived"], corpus_chunks["doc_020_register"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Which document supersedes the Archived Travel Policy 2024 , and what was its lodging cap?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="policy_compliance"
        )
        ans = envelope["answer"]

        first_sent = ans.split(". ")[0]
        assert "doc-021" in first_sent.lower() or "doc-021" in ans.lower()
        assert "$150" in first_sent or "$150" in ans
        assert "authoritative operational rule" not in ans.lower()

    def test_defect_7_internal_memo_non_authoritative_no_security_fallback(self, mock_workspace, corpus_chunks):
        """
        Defect 7 (Q7):
        - Old bug: Overbroad action gate triggered hallucinated security assessment fallback.
        - Fix: Direct answer: No, travel coordinator should not use $250; memo is informational planning note;
          DOC-002 governs at $220; does NOT route to Security Team.
        """
        chunks = [corpus_chunks["doc_011_memo"], corpus_chunks["doc_002_hotel"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="An internal memo states the hotel nightly cap is $250. Should a travel coordinator use this figure to approve a booking?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="policy_compliance"
        )
        ans = envelope["answer"]

        first_sent = ans.split(". ")[0]
        assert any(w in first_sent.lower() for w in ["no", "should not", "cannot"])
        assert "informational" in ans.lower() or "planning" in ans.lower() or "non-authoritative" in ans.lower()
        assert "$220" in ans
        assert "security team" not in ans.lower()
        assert "formal_security_assessment_report" not in ans.lower()
        assert "authoritative operational rule" not in ans.lower()

    def test_defect_8_invoice_vs_contract_discrepancies_and_arithmetic(self, mock_workspace, corpus_chunks):
        """
        Defect 8 (Q8):
        - Old bug: Missed date and amount schedule discrepancies, hallucinated that contract 'proposes $48'.
        - Fix: Direct answer: Yes, material discrepancies exist:
          1) Date: Oct 15, 2026 predates Jan 1, 2027;
          2) Amount: $4,800 billed vs $48,000 annual ($12,000 quarterly);
          3) Status: unapproved draft. Does not hallucinate '$48'.
        """
        chunks = [corpus_chunks["doc_010_invoice"], corpus_chunks["doc_009_contract"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Review the Atlas Services Invoice 2026-041 . Is there any discrepancy between this invoice and the Vendor Contract ?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="contract_compliance"
        )
        ans = envelope["answer"]

        first_sent = ans.split(". ")[0]
        assert any(w in first_sent.lower() for w in ["yes", "discrepanc"])
        assert "october" in ans.lower() or "2026" in ans
        assert "january" in ans.lower() or "2027" in ans
        assert "$4,800" in ans
        assert "$48,000" in ans or "$12,000" in ans
        # Must not hallucinate '$48'
        assert not re.search(r'\bproposes\s+\$48\b', ans)
        assert "authoritative operational rule" not in ans.lower()

    def test_defect_9_carla_reyes_access_no_unrelated_employees(self, mock_workspace, corpus_chunks):
        """
        Defect 9 (Q9):
        - Old bug: Dumped entire table of unrelated employees (Alice Morgan, Ben Carter).
        - Fix: Direct answer states Carla Reyes currently has no workspace access permissions granted;
          status PENDING, not effective; does NOT dump Alice Morgan or Ben Carter.
        """
        chunks = [corpus_chunks["doc_017_access"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What are the specific workspace access permissions currently granted to Carla Reyes?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="general_inquiry"
        )
        ans = envelope["answer"]

        first_sent = ans.split(". ")[0]
        assert "carla reyes" in first_sent.lower()
        assert any(w in first_sent.lower() for w in ["no", "none", "not granted", "pending"])
        assert "alice morgan" not in ans.lower()
        assert "ben carter" not in ans.lower()
        assert "authoritative operational rule" not in ans.lower()

    def test_defect_10_doc021_exact_text_negative_retrieval(self, mock_workspace, corpus_chunks):
        """
        Defect 10 (Q10):
        - Old bug: Regurgitated metadata without stating that text of DOC-021 is missing from dataset.
        - Fix: Direct answer states exact text is not available / not present in active knowledge base;
          register establishes reference only; does not hallucinate policy text.
        """
        chunks = [corpus_chunks["doc_016_archived"], corpus_chunks["doc_020_register"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the exact text of the Travel & Expense Policy (2025) that replaced the 2024 policy?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="policy_compliance"
        )
        ans = envelope["answer"]

        first_sent = ans.split(". ")[0]
        assert any(w in first_sent.lower() for w in ["not available", "not present", "not supplied", "could not be verified"])
        assert "authoritative operational rule" not in ans.lower()

    def test_defect_11_emergency_procurement_three_conditions(self, mock_workspace, corpus_chunks):
        """
        Defect 11 (Q11):
        - Old bug: Dumped meeting minutes header from DOC-019.
        - Fix: Direct answer returns all 3 mandatory conditions from DOC-004:
          1) Written CFO approval before purchase;
          2) Documented emergency describing circumstances, urgency, and need;
          3) Retrospective review within 2 business days.
        """
        chunks = [corpus_chunks["doc_004_emergency"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What are the three mandatory conditions that must be satisfied to use the Emergency Procurement Exception?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="procurement_governance"
        )
        ans = envelope["answer"]

        assert "cfo" in ans.lower()
        assert "documented emergency" in ans.lower() or "urgency" in ans.lower()
        assert "retrospective review" in ans.lower() or "two business days" in ans.lower() or "2 business days" in ans.lower()
        assert "authoritative operational rule" not in ans.lower()

    def test_defect_12_lost_receipt_process_complete_sentence(self, mock_workspace, corpus_chunks):
        """
        Defect 12 (Q12):
        - Old bug: Fragmented broken sentence citing historical 2024 policy.
        - Fix: Grammatical sentence stating process: submit claim within 15 calendar days,
          accompanied by written explanation and manager approval; reimbursement not guaranteed ($30 > $25 threshold).
        """
        chunks = [corpus_chunks["doc_002_lost_receipt"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="An employee loses a $30 receipt for a business dinner. What is the required process to attempt reimbursement?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="policy_compliance"
        )
        ans = envelope["answer"]

        first_sent = ans.split(". ")[0]
        assert "15" in first_sent
        assert "written explanation" in ans.lower()
        assert "manager approval" in ans.lower()
        assert "not guaranteed" in ans.lower() or "deny" in ans.lower()
        assert "2024" not in ans
        assert "authoritative operational rule" not in ans.lower()


# ==============================================================================
# RULE 3 & 10: MISSING REQUIRED FACT VALIDATION DOWNGRADE TESTS
# ==============================================================================

@pytest.mark.django_db
class TestMissingRequiredFactValidation:

    def test_missing_expiry_date_prevents_supported_result(self, mock_workspace):
        """
        Rule 3 & 10:
        User asks for carry forward quantity AND expiration date.
        If evidence only contains the carryover quantity (5 days) but lacks the expiration date,
        the validator MUST downgrade state to INSUFFICIENT (ASK_USER).
        A SUPPORTED result is strictly forbidden.
        """
        chunk_without_expiry = {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-005 — Partial Leave Policy",
            "document_status": "approved",
            "authority_level": 7,
            "page_number": 1,
            "score": 0.95,
            "text": "An eligible employee may carry forward up to 5 unused working days of annual leave into the next leave year."
        }

        # Generated answer only includes what was found
        answer = "An eligible employee may carry forward up to 5 unused working days of annual leave."

        val_result = AnswerCompletenessValidator.validate(
            query="What is the maximum number of unused annual leave days an employee can carry forward, and when do they expire?",
            answer=answer,
            candidate_chunks=[chunk_without_expiry],
            current_state=Verdict.SUPPORTED.value
        )

        # Missing required fact must prevent SUPPORTED!
        assert not val_result.is_valid
        assert val_result.is_downgraded
        assert val_result.new_state == Verdict.INSUFFICIENT.value
        assert val_result.new_directive == Directive.ASK_USER.value
        assert any("expiry" in m["requirement"] for m in val_result.evidence_missing)
        assert "missing from available evidence" in val_result.new_answer or "missing from available documentation" in val_result.new_answer

    def test_missing_retention_trigger_prevents_supported_result(self, mock_workspace):
        """
        Rule 3 & 10:
        User asks for retention duration AND trigger.
        If evidence only contains the duration (2 years) but lacks the trigger,
        the validator MUST downgrade state to INSUFFICIENT.
        """
        chunk_without_trigger = {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-008 — Incomplete Retention Schedule",
            "document_status": "approved",
            "authority_level": 7,
            "page_number": 1,
            "score": 0.95,
            "text": "Audit events must be retained for a mandatory retention period of exactly 2 years."
        }

        answer = "Under the Records Retention Schedule, audit events must be retained for 2 years."

        val_result = AnswerCompletenessValidator.validate(
            query="According to the Records Retention Schedule, how long must 'Audit events' (security logs, access events) be retained, and what is the trigger?",
            answer=answer,
            candidate_chunks=[chunk_without_trigger],
            current_state=Verdict.SUPPORTED.value
        )

        assert not val_result.is_valid
        assert val_result.is_downgraded
        assert val_result.new_state == Verdict.INSUFFICIENT.value
        assert val_result.new_directive == Directive.ASK_USER.value
        assert any("trigger" in m["requirement"] for m in val_result.evidence_missing)


# ==============================================================================
# RULE 10: DETERMINISTIC FACTUALITY & CITATION INTEGRITY TESTS
# ==============================================================================

@pytest.mark.django_db
class TestDeterministicFactualityAndAntiHallucination:

    def test_deterministic_dollar_amount_validation_catches_hallucinations(self):
        """
        Rule 10:
        If an answer introduces an invented dollar amount ($48) that does not exist in
        candidate evidence and is not a valid calculation, the validator must flag it.
        """
        chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "DOC-010 — Invoice",
                "text": "Invoice 2026-041 totals $4,800.00."
            }
        ]
        hallucinated_answer = "The agreement proposes $48, but the invoice bills $4,800."

        val_res = AnswerQualityValidator.validate(
            query="Review the Atlas Services Invoice. Is there any discrepancy?",
            answer=hallucinated_answer,
            citations=[],
            candidate_chunks=chunks
        )

        assert any("UNGROUNDED_AMOUNT_DETECTED" in f and "$48" in f for f in val_res.flags)

    def test_anti_robotic_remediation_sanitizes_boilerplate(self):
        """
        Rule 2:
        If robotic phrase 'this is the authoritative operational rule' somehow leaks into answer,
        AnswerQualityValidator must remediate it.
        """
        robotic_answer = "The annual leave allowance is 20 days. According to DOC-008, this is the authoritative operational rule."
        val_res = AnswerQualityValidator.validate(
            query="What is the leave allowance?",
            answer=robotic_answer,
            citations=[],
            candidate_chunks=[{"text": "The annual leave allowance is 20 days."}]
        )

        assert "this is the authoritative operational rule" not in val_res.sanitized_answer
        assert val_res.remediation_applied
        assert any("ROBOTIC_PHRASE_REMEDIATED" in f for f in val_res.flags)

    def test_strict_separation_envelope_integrity(self, mock_workspace, corpus_chunks):
        """
        Rule 9:
        Internal diagnostics, scores, trace IDs, and layer timings must remain in the
        envelope metadata (layers_breakdown, model_metrics), NOT in the human-facing answer.
        """
        chunks = [corpus_chunks["doc_005_leave"]]
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the maximum number of unused annual leave days an employee can carry forward, and when do they expire?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="policy_compliance"
        )
        answer = envelope["answer"]

        # Human answer must not leak internal implementation details
        assert "trace-" not in answer
        assert "timings_ms" not in answer
        assert "token_count" not in answer
        assert "l1_decision_intelligence" not in answer

        # But envelope strictly preserves authorized audit data
        assert "trace_id" in envelope
        assert "layers_breakdown" in envelope
        assert "l0_observability" in envelope["layers_breakdown"]
        assert "timings_ms" in envelope["layers_breakdown"]["l0_observability"]

"""
LORE Enterprise — 12-Question Benchmark Regression Test Suite
Corpus: Lore_Dataset.zip (DOC-001 through DOC-020)
Verifies:
- All 12 benchmark questions return factual, authoritative answers.
- Direct answers with key values/decisions in first sentence.
- Source-grounded citations without hallucinated documents.
- Proper handling of drafts, future-effective amendments, expired policies,
  missing DOC-021 content, pending access requests, and non-authoritative memos.
"""

import uuid
import pytest
from apps.decisions.synthesizer import ConciseAnswerSynthesizer


@pytest.fixture
def benchmark_chunks():
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
            "authority_level": 5,
            "page_number": 1,
            "score": 0.88,
            "text": "Policy Amendment: Hotel accommodation reimbursement cap increased to $240 per night, effective January 1, 2027."
        },
        "doc_016_archived": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-016_Archived_Travel_Policy_2024.pdf",
            "document_status": "superseded",
            "is_superseded": True,
            "authority_level": 2,
            "page_number": 1,
            "score": 0.90,
            "text": "Archived Travel Policy 2024. Superseded by DOC-021 (Travel & Expense Policy 2025) on January 1, 2025. Historical lodging cap was USD $150 per night."
        },
        "doc_017_access": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-017_Workspace_Access_Request.docx",
            "document_status": "submitted",
            "authority_level": 3,
            "page_number": 1,
            "score": 0.92,
            "text": "Carla Reyes submitted request for Workspace Administrator role in Identity & Access Governance and Product Engineering. Approval Status: PENDING. Effective: No."
        },
        "doc_019_minutes": {
            "document_id": str(uuid.uuid4()),
            "document_title": "DOC-019_Procurement_Review_Minutes.docx",
            "document_status": "approved",
            "authority_level": 4,
            "page_number": 1,
            "score": 0.94,
            "text": "Procurement Review Meeting Minutes. $32,000 CNC vertical milling machine purchase: Committee deferred purchase authorization due to missing CFO approval and Finance objection regarding unsupported $14,000 annual savings."
        }
    }


class TestBenchmark12Corpus:

    def test_q1_annual_leave_carryover(self, benchmark_chunks):
        query = "What is the maximum number of unused annual leave days an employee can carry forward, and when do they expire?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_005_leave"]],
            conflicts=[],
            state="qualified"
        )
        assert "5" in ans
        assert "March 31" in ans
        assert "DOC-005" in ans
        assert "draft" in ans.lower()

    def test_q2_audit_retention_schedule(self, benchmark_chunks):
        query = 'According to the Records Retention Schedule, how long must "Audit events" (security logs, access events) be retained, and what is the trigger?'
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_008_retention"]],
            conflicts=[],
            state="qualified"
        )
        assert "2 years" in ans
        assert "event timestamp" in ans.lower()
        assert "DOC-008" in ans

    def test_q3_procurement_cnc_minutes(self, benchmark_chunks):
        query = "Can the $32,000 CNC vertical milling machine purchase be authorized based on the Procurement Review Minutes ? Why or why not?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_019_minutes"]],
            conflicts=[],
            state="supported"
        )
        assert "No" in ans
        assert "defer" in ans.lower()
        assert "CFO approval" in ans
        assert "$14,000" in ans
        assert "DOC-019" in ans

    def test_q4_hotel_450_two_nights_non_compliant(self, benchmark_chunks):
        query = "An employee submits an expense claim for a $450 hotel stay for 2 nights in August 2026. They have manager approval but no written exception from Finance. Is this compliant?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_002_hotel"]],
            conflicts=[],
            state="supported"
        )
        assert "No" in ans
        assert "not compliant" in ans.lower()
        assert "$220" in ans
        assert "Finance" in ans
        assert "DOC-002" in ans

    def test_q5_hotel_accommodation_cap_nov_2026(self, benchmark_chunks):
        query = "What is the maximum reimbursable hotel accommodation cost per night for business travel occurring on November 15, 2026?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_002_hotel"], benchmark_chunks["doc_015_amendment"]],
            conflicts=[],
            state="supported"
        )
        assert "$220" in ans
        assert "DOC-002" in ans
        assert "DOC-015" in ans
        assert "does not affect" in ans or "January 1, 2027" in ans

    def test_q6_superseded_archived_policy_2024(self, benchmark_chunks):
        query = "Which document supersedes the Archived Travel Policy 2024 , and what was its lodging cap?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_016_archived"]],
            conflicts=[],
            state="qualified"
        )
        assert "DOC-021" in ans
        assert "$150" in ans
        assert "DOC-016" in ans

    def test_q7_internal_memo_non_authoritative(self, benchmark_chunks):
        query = "An internal memo states the hotel nightly cap is $250. Should a travel coordinator use this figure to approve a booking?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_011_memo"], benchmark_chunks["doc_002_hotel"]],
            conflicts=[],
            state="qualified"
        )
        assert "No" in ans
        assert "DOC-011" in ans
        assert "DOC-002" in ans
        assert "$220" in ans

    def test_q8_invoice_vs_contract_discrepancies(self, benchmark_chunks):
        query = "Review the Atlas Services Invoice 2026-041 . Is there any discrepancy between this invoice and the Vendor Contract ?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_010_invoice"], benchmark_chunks["doc_009_contract"]],
            conflicts=[],
            state="supported"
        )
        assert "discrepanc" in ans.lower()
        assert "15 October 2026" in ans or "Date" in ans
        assert "$4,800" in ans or "Amount" in ans
        assert "draft" in ans.lower()
        assert "DOC-010" in ans
        assert "DOC-009" in ans

    def test_q9_carla_reyes_workspace_access(self, benchmark_chunks):
        query = "What are the specific workspace access permissions currently granted to Carla Reyes?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_017_access"]],
            conflicts=[],
            state="supported"
        )
        assert "no workspace access permissions" in ans.lower()
        assert "PENDING" in ans
        assert "DOC-017" in ans

    def test_q10_doc021_exact_text_missing(self, benchmark_chunks):
        query = "What is the exact text of the Travel & Expense Policy (2025) that replaced the 2024 policy?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_016_archived"]],
            conflicts=[],
            state="supported"
        )
        assert "DOC-021" in ans
        assert "not available" in ans.lower() or "not present" in ans.lower()

    def test_q11_emergency_procurement_conditions(self, benchmark_chunks):
        query = "What are the three mandatory conditions that must be satisfied to use the Emergency Procurement Exception?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_004_emergency"]],
            conflicts=[],
            state="supported"
        )
        assert "three mandatory conditions" in ans.lower()
        assert "CFO approval" in ans
        assert "Documented emergency" in ans
        assert "Retrospective review" in ans
        assert "DOC-004" in ans

    def test_q12_lost_receipt_process(self, benchmark_chunks):
        query = "An employee loses a $30 receipt for a business dinner. What is the required process to attempt reimbursement?"
        ans = ConciseAnswerSynthesizer.synthesize(
            query=query,
            retrieved_chunks=[benchmark_chunks["doc_002_lost_receipt"]],
            conflicts=[],
            state="supported"
        )
        assert "15 calendar days" in ans
        assert "written explanation" in ans.lower()
        assert "manager approval" in ans.lower()
        assert "DOC-002" in ans

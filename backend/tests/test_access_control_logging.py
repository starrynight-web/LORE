"""
LORE Enterprise — Access Control Logging & Evidence Relevance Regression Test Suite

Regression tests covering the 7 requirements:
1. Access-control logging question retrieves relevant Information Security Policy evidence.
2. Travel-expense policy metadata does not create a false access-control conflict.
3. An actual conflict between relevant, applicable sources is still detected.
4. A draft source is not silently represented as approved.
5. Irrelevant evidence is excluded from the final citations.
6. Every answer claim is supported by its cited passage.
7. Concise answers and expandable evidence work without breaking existing functionality.
"""

import uuid
import pytest
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument
from apps.knowledge.models import DocumentChunk
from apps.governance.models import ConflictRecord
from apps.governance.contract import GovernanceRequest
from apps.governance.layers import EnterpriseGovernanceEngine, AuthorityLayer
from apps.governance.evidence import EvidencePresentationEngine
from apps.decisions.synthesizer import ConciseAnswerSynthesizer


@pytest.fixture
def access_control_workspace(db):
    org = Organization.objects.create(name="Access Control Org", slug=f"ac-org-{uuid.uuid4().hex[:6]}")
    ws = Workspace.objects.create(name="Access Control Workspace", slug=f"ac-ws-{uuid.uuid4().hex[:6]}", organization=org)
    return ws


# ==============================================================================
# TEST 1: The access-control logging question retrieves relevant Information Security Policy evidence
# ==============================================================================
@pytest.mark.django_db
def test_access_control_logging_retrieves_information_security_policy(access_control_workspace):
    ws = access_control_workspace
    query = "What access-control actions must be logged?"

    # Candidate chunks simulating hybrid retrieval return set
    chunks = [
        {
            "chunk_id": "chk-doc007-sec7",
            "document_id": "doc-007-sec",
            "document_code": "DOC-007",
            "document_title": "DOC-007 — Information_Security_Policy.pdf",
            "document_version": 1,
            "authority_level": 6,
            "document_status": "draft",
            "is_draft": True,
            "page_number": 1,
            "heading_path": "Section 7: Audit Logging and Monitoring",
            "text": (
                "7. Audit Logging and Monitoring Systems that process confidential or business-critical information "
                "must record relevant security events, including successful and failed authentication, "
                "access to privileged functions, permission changes, and significant changes to protected records "
                "where technically feasible. Logs must include timestamps and user or service identity. "
                "DOC-007 | Information Security Policy | Draft for review Page 1"
            ),
            "score": 1.01
        },
        {
            "chunk_id": "chk-doc002-travel",
            "document_id": "doc-002-trv",
            "document_code": "DOC-002",
            "document_title": "DOC-002 — Travel_Expense_Policy_v2.pdf",
            "document_version": 2,
            "authority_level": 6,
            "document_status": "approved",
            "page_number": 2,
            "heading_path": "Section 3 > Travel Approvals",
            "text": "All non-standard flight bookings require prior VP approval and must be documented in Concur.",
            "score": 0.45
        },
        {
            "chunk_id": "chk-doc017-workspace",
            "document_id": "doc-017-ws",
            "document_code": "DOC-017",
            "document_title": "DOC-017_Workspace_Access_Request",
            "document_version": 1,
            "authority_level": 3,
            "document_status": "ready",
            "page_number": 1,
            "heading_path": "Access Request Form",
            "text": "Workspace Access Request Register: Employee must submit approval from departmental manager.",
            "score": 0.35
        }
    ]

    res = EnterpriseGovernanceEngine.evaluate(
        query=query,
        retrieved_chunks=chunks,
        workspace=ws
    )

    assert res['state'] in ('supported', 'qualified')
    assert res['directive'] == 'proceed_and_cite'
    assert len(res['citations']) == 1
    primary_cit = res['citations'][0]
    assert "DOC-007" in primary_cit['document_title']
    assert "successful and failed authentication" in primary_cit['shortest_passage'].lower()
    assert "privileged functions" in primary_cit['shortest_passage'].lower()
    assert "permission changes" in primary_cit['shortest_passage'].lower()


# ==============================================================================
# TEST 2: Travel-expense policy metadata does not create a false access-control conflict
# ==============================================================================
@pytest.mark.django_db
def test_travel_expense_metadata_does_not_create_false_access_control_conflict(access_control_workspace):
    ws = access_control_workspace
    query = "What access-control actions must be logged?"

    # Create SourceDocuments in DB with seeded conflict between DOC-002 and DOC-017
    doc_trv = SourceDocument.objects.create(
        organization=ws.organization,
        workspace=ws,
        title="DOC-002 — Travel_Expense_Policy_v2.pdf",
        original_filename="doc002.pdf",
        mime_type="application/pdf",
        file_size=1024,
        file_hash="hash-doc002-test",
        status="ready",
        authority_level=6
    )
    doc_req = SourceDocument.objects.create(
        organization=ws.organization,
        workspace=ws,
        title="DOC-017_Workspace_Access_Request",
        original_filename="doc017.pdf",
        mime_type="application/pdf",
        file_size=1024,
        file_hash="hash-doc017-test",
        status="ready",
        authority_level=3
    )
    doc_sec = SourceDocument.objects.create(
        organization=ws.organization,
        workspace=ws,
        title="DOC-007 — Information_Security_Policy.pdf",
        original_filename="doc007.pdf",
        mime_type="application/pdf",
        file_size=1024,
        file_hash="hash-doc007-test",
        status="ready",
        authority_level=6
    )

    # Seed conflict between travel policy and workspace request form in database
    ConflictRecord.objects.create(
        workspace=ws,
        source_a=doc_trv,
        source_b=doc_req,
        claim_a="Requires VP approval for non-standard travel bookings",
        claim_b="Workspace access requests require department manager approval",
        resolution_status="unresolved",
        resolution_notes="Disagreement on approval delegation hierarchy"
    )

    chunks = [
        {
            "chunk_id": "chk-sec",
            "document_id": str(doc_sec.id),
            "document_title": doc_sec.title,
            "authority_level": 6,
            "document_status": "draft",
            "is_draft": True,
            "page_number": 1,
            "text": "7. Audit Logging and Monitoring: Systems must record relevant security events, including successful and failed authentication, privileged functions, and permission changes. Draft for review.",
            "score": 0.98
        },
        {
            "chunk_id": "chk-trv",
            "document_id": str(doc_trv.id),
            "document_title": doc_trv.title,
            "authority_level": 6,
            "document_status": "approved",
            "page_number": 1,
            "text": "Travel bookings require prior VP approval.",
            "score": 0.40
        },
        {
            "chunk_id": "chk-req",
            "document_id": str(doc_req.id),
            "document_title": doc_req.title,
            "authority_level": 3,
            "document_status": "ready",
            "page_number": 1,
            "text": "Workspace access requests require manager approval.",
            "score": 0.30
        }
    ]

    res = EnterpriseGovernanceEngine.evaluate(
        query=query,
        retrieved_chunks=chunks,
        workspace=ws
    )

    # MUST NOT be flagged as conflicting!
    assert res['state'] != 'conflicting', f"Expected non-conflicting state, got {res['state']}: {res['answer']}"
    assert res['directive'] == 'proceed_and_cite'
    assert "Contradictory authoritative sources detected" not in res['answer']
    assert res['validation_signals']['conflict'] is True


# ==============================================================================
# TEST 3: An actual conflict between relevant, applicable sources is still detected
# ==============================================================================
@pytest.mark.django_db
def test_actual_conflict_between_relevant_sources_still_detected(access_control_workspace):
    ws = access_control_workspace
    query = "What is the mandatory retention period for employee access audit logs?"

    chunks = [
        {
            "chunk_id": "chk-ret-a",
            "document_id": "doc-ret-a",
            "document_title": "Global Security Audit Standard",
            "authority_level": 6,
            "document_status": "approved",
            "page_number": 4,
            "text": "Section 4.2: Audit logs for employee access must be retained for exactly 3 years.",
            "score": 0.92
        },
        {
            "chunk_id": "chk-ret-b",
            "document_id": "doc-ret-b",
            "document_title": "Enterprise Compliance Records Policy",
            "authority_level": 6,
            "document_status": "approved",
            "page_number": 8,
            "text": "Section 8.1: Audit logs for employee access must be retained for exactly 7 years.",
            "score": 0.90
        }
    ]

    res = EnterpriseGovernanceEngine.evaluate(
        query=query,
        retrieved_chunks=chunks,
        workspace=ws
    )

    # Genuinely incompatible retention periods at equal Rank 6 must trigger conflicting state
    assert res['state'] == 'conflicting'
    assert res['directive'] == 'ask_user'
    assert "Contradictory authoritative sources detected" in res['answer']
    assert res['validation_signals']['conflict'] is False


# ==============================================================================
# TEST 4: A draft source is not silently represented as approved
# ==============================================================================
@pytest.mark.django_db
def test_draft_source_not_silently_represented_as_approved(access_control_workspace):
    ws = access_control_workspace
    query = "What access-control actions must be logged?"

    chunks = [
        {
            "chunk_id": "chk-sec-draft",
            "document_id": "doc-007-sec",
            "document_title": "DOC-007 — Information_Security_Policy.pdf",
            "authority_level": 6,
            "document_status": "draft",
            "is_draft": True,
            "page_number": 1,
            "text": "Section 7: Audit Logging and Monitoring. Systems must record relevant security events. Status: Draft for review.",
            "score": 0.95
        }
    ]

    res = EnterpriseGovernanceEngine.evaluate(
        query=query,
        retrieved_chunks=chunks,
        workspace=ws
    )

    assert len(res['citations']) == 1
    cit = res['citations'][0]
    # Status must strictly be draft
    assert cit['document_status'] == 'draft'
    # Material limitation must disclose non-binding draft status
    assert "Non-binding" in (cit.get('limitation') or '')
    assert "draft" in (cit.get('limitation') or '').lower()
    # Answer text must disclose draft status
    assert "draft" in res['answer'].lower() or "not yet been formally approved" in res['answer'].lower()
    # Authority validation signal must be False for unapproved draft
    assert res['validation_signals']['authority'] is False


# ==============================================================================
# TEST 5: Irrelevant evidence is excluded from the final citations
# ==============================================================================
@pytest.mark.django_db
def test_irrelevant_evidence_excluded_from_final_citations(access_control_workspace):
    ws = access_control_workspace
    query = "What access-control actions must be logged?"

    chunks = [
        {
            "chunk_id": "chk-sec-relevant",
            "document_id": "doc-007-sec",
            "document_title": "DOC-007 — Information_Security_Policy.pdf",
            "authority_level": 6,
            "document_status": "draft",
            "is_draft": True,
            "page_number": 1,
            "text": "7. Audit Logging and Monitoring Systems that process confidential or business-critical information must record relevant security events, including successful and failed authentication, access to privileged functions, permission changes, and significant changes to protected records where technically feasible.",
            "score": 1.01
        },
        {
            "chunk_id": "chk-trv-irrelevant",
            "document_id": "doc-002-trv",
            "document_title": "DOC-002 — Travel_Expense_Policy_v2.pdf",
            "authority_level": 6,
            "document_status": "approved",
            "page_number": 3,
            "text": "Itemized meal receipts must be submitted within 14 calendar days of trip completion.",
            "score": 0.35
        },
        {
            "chunk_id": "chk-ret-irrelevant",
            "document_id": "doc-008-ret",
            "document_title": "DOC-008 — Records_Retention_Schedule.xlsx",
            "authority_level": 5,
            "document_status": "approved",
            "page_number": 1,
            "text": "Audit logs | Security logs, access events | 2 years | Event timestamp | Controlled deletion under approved IT procedures.",
            "score": 0.45
        },
        {
            "chunk_id": "chk-req-irrelevant",
            "document_id": "doc-017-ws",
            "document_title": "DOC-017_Workspace_Access_Request",
            "authority_level": 3,
            "document_status": "ready",
            "page_number": 1,
            "text": "NORTHSTAR MANUFACTURING LTD. Workspace Access Request Register. Departmental Manager approval required.",
            "score": 0.25
        }
    ]

    res = EnterpriseGovernanceEngine.evaluate(
        query=query,
        retrieved_chunks=chunks,
        workspace=ws
    )

    # Exactly 1 citation must be returned
    assert len(res['citations']) == 1
    cited_doc = res['citations'][0]
    assert cited_doc['document_title'] == "DOC-007 — Information_Security_Policy.pdf"

    # Verify that all unrelated documents are strictly excluded
    cited_titles = [c['document_title'] for c in res['citations']]
    assert "DOC-002 — Travel_Expense_Policy_v2.pdf" not in cited_titles
    assert "DOC-008 — Records_Retention_Schedule.xlsx" not in cited_titles
    assert "DOC-017_Workspace_Access_Request" not in cited_titles


# ==============================================================================
# TEST 6: Every answer claim is supported by its cited passage
# ==============================================================================
@pytest.mark.django_db
def test_every_answer_claim_supported_by_cited_passage(access_control_workspace):
    ws = access_control_workspace
    query = "What access-control actions must be logged?"

    chunks = [
        {
            "chunk_id": "chk-doc007-sec7",
            "document_id": "doc-007-sec",
            "document_title": "DOC-007 — Information_Security_Policy.pdf",
            "authority_level": 6,
            "document_status": "draft",
            "is_draft": True,
            "page_number": 1,
            "text": (
                "7. Audit Logging and Monitoring Systems that process confidential or business-critical information "
                "must record relevant security events, including successful and failed authentication, "
                "access to privileged functions, permission changes, and significant changes to protected records "
                "where technically feasible."
            ),
            "score": 1.01
        }
    ]

    res = EnterpriseGovernanceEngine.evaluate(
        query=query,
        retrieved_chunks=chunks,
        workspace=ws
    )

    ans = res['answer']
    cit = res['citations'][0]
    passage = cit['shortest_passage']

    # 4 required access-control actions in answer
    required_claims = [
        "authentication",
        "privileged functions",
        "permission changes",
        "significant changes to protected records"
    ]

    for claim in required_claims:
        assert claim in ans.lower(), f"Answer missing expected claim: {claim}"
        assert claim in passage.lower(), f"Cited passage does not support answer claim: {claim}"

    # Verify "where technically feasible" qualification is preserved
    assert "feasible" in ans.lower()
    assert "feasible" in passage.lower()

    # Entailment signal must be True
    assert res['validation_signals']['entailment'] is True


# ==============================================================================
# TEST 7: Concise answers and expandable evidence work without breaking existing functionality
# ==============================================================================
@pytest.mark.django_db
def test_concise_answers_and_expandable_evidence_work(access_control_workspace):
    ws = access_control_workspace
    query = "What access-control actions must be logged?"

    chunks = [
        {
            "chunk_id": "chk-doc007-sec7",
            "document_id": "doc-007-sec",
            "document_title": "DOC-007 — Information_Security_Policy.pdf",
            "authority_level": 6,
            "document_status": "draft",
            "is_draft": True,
            "page_number": 1,
            "text": "7. Audit Logging and Monitoring Systems that process confidential or business-critical information must record relevant security events, including successful and failed authentication, access to privileged functions, permission changes, and significant changes to protected records where technically feasible.",
            "score": 1.01
        }
    ]

    res = EnterpriseGovernanceEngine.evaluate(
        query=query,
        retrieved_chunks=chunks,
        workspace=ws
    )

    # 1. Answer conciseness: Leads with direct factual answer (approx 1-4 sentences / bullet list)
    lines = [line.strip() for line in res['answer'].split('\n') if line.strip()]
    assert len(lines) <= 7, f"Answer is not concise: {res['answer']}"
    assert "Systems that process confidential or business-critical information" in res['answer']

    # 2. Expandable evidence proof structure
    assert 'citations' in res
    assert len(res['citations']) == 1
    cit = res['citations'][0]
    required_keys = [
        'document_title', 'document_id', 'page_number', 'document_status',
        'shortest_passage', 'supported_claim', 'limitation'
    ]
    for k in required_keys:
        assert k in cit, f"Citation dictionary missing required proof field: {k}"

    assert cit['page_number'] == 1
    assert cit['document_status'] == 'draft'
    assert len(cit['shortest_passage']) > 20
    assert cit['supported_claim'] is not None

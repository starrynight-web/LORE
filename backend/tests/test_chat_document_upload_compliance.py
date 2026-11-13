import io
import uuid
from typing import Any
import pytest
import fitz
import docx
import openpyxl
from datetime import datetime
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.knowledge.models import DocumentChunk
from apps.decisions.models import Conversation, ChatMessage
from apps.decisions.services import ConversationService
from apps.ingestion.pipeline.ephemeral import extract_ephemeral_document


def create_in_memory_pdf(text: str = "Company Project Proposal\nBudget: $5000\nStatus: Pending Review") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 72), text, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def create_in_memory_docx(text: str = "Quarterly Consulting Proposal\nProposed cost: $4000") -> bytes:
    doc = docx.Document()
    doc.add_heading("Consulting Agreement Proposal", 0)
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def create_in_memory_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws: Any = wb.active or wb.create_sheet(title="Budget Breakdown")
    ws.title = "Budget Breakdown"
    ws.append(["Expense Item", "Category", "Amount USD"])
    ws.append(["Airfare", "Travel", 450])
    ws.append(["Hotel Stay", "Lodging", 300])
    ws.append(["Meal Allowance", "Per Diem", 60])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def compliance_fixture(db):
    uid = uuid.uuid4().hex[:6]
    user = User.objects.create_user(
        username=f"audit_user_{uid}",
        email=f"audit_{uid}@lore.test",
        password="Password123!"
    )

    org = Organization.objects.create(name=f"Compliance Corp {uid}", slug=f"compliance-corp-{uid}")
    OrganizationMembership.objects.create(organization=org, user=user, role='member')

    ws = Workspace.objects.create(name=f"Audit Workspace {uid}", slug=f"audit-ws-{uid}", organization=org)
    WorkspaceMembership.objects.create(workspace=ws, user=user, role='member')

    # Seed authoritative company travel & expense policy in the workspace
    policy_doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Corporate Travel and Expense Policy 2026",
        original_filename="corp_travel_policy_2026.pdf",
        mime_type="application/pdf",
        file_size=2048,
        file_hash=f"hash_{uid}_policydoc1234567890abcdef",
        status="ready",
        authority_level=7,
        current_version_number=1,
        effective_date=timezone.now()
    )
    ver = DocumentVersion.objects.create(
        document=policy_doc,
        version_number=1,
        file_hash=policy_doc.file_hash,
        is_current=True
    )

    # Chunk specifying meal allowance cap of $75 and hotel cap of $350
    DocumentChunk.objects.create(
        organization=org,
        workspace=ws,
        document=policy_doc,
        document_version=ver,
        chunk_index=0,
        contextual_header="Travel Expenses > Daily Allowances",
        text="The approved maximum daily meal allowance is $75 per day. Any meal expense exceeding $75 is strictly prohibited and not reimbursable. Hotel accommodations must not exceed $350 per night.",
        token_count=35,
        page_number=1
    )

    # Chunk specifying airfare economy class requirement
    DocumentChunk.objects.create(
        organization=org,
        workspace=ws,
        document=policy_doc,
        document_version=ver,
        chunk_index=1,
        contextual_header="Travel Expenses > Flight Standards",
        text="All commercial domestic and short-haul flights must be booked in economy class. Business class is not permitted unless flight duration exceeds 8 continuous hours.",
        token_count=30,
        page_number=2
    )

    conv = Conversation.objects.create(
        organization=org,
        workspace=ws,
        user=user,
        title="Policy Review Thread"
    )

    return {
        "user": user,
        "org": org,
        "ws": ws,
        "policy_doc": policy_doc,
        "conversation": conv
    }


@pytest.mark.django_db
class TestChatDocumentUploadCompliance:

    def test_ephemeral_extraction_pdf_preserves_zero_db_persistence(self, compliance_fixture):
        """Validates in-memory extraction of PDF proposals without database records or chunking."""
        initial_doc_count = SourceDocument.objects.count()
        initial_chunk_count = DocumentChunk.objects.count()

        pdf_bytes = create_in_memory_pdf("Vendor Proposal: IT Cloud Migration\nEstimated Cost: $15,000\nDeliverables: AWS to GCP")
        uploaded = SimpleUploadedFile("vendor_proposal.pdf", pdf_bytes, content_type="application/pdf")

        result = extract_ephemeral_document(uploaded, "vendor_proposal.pdf")

        assert result["filename"] == "vendor_proposal.pdf"
        assert result["doc_type"] == "pdf"
        assert "IT Cloud Migration" in result["text"]
        assert result["pages_count"] >= 1
        assert result["file_size"] == len(pdf_bytes)

        # STRICT INVARIANT: Zero DB objects created
        assert SourceDocument.objects.count() == initial_doc_count
        assert DocumentChunk.objects.count() == initial_chunk_count

    def test_ephemeral_extraction_docx_and_xlsx(self, compliance_fixture):
        """Validates in-memory extraction of Office documents (DOCX and XLSX)."""
        # 1. DOCX
        docx_bytes = create_in_memory_docx("Consultant travel budget for conference: $500 total.")
        uploaded_docx = SimpleUploadedFile("consultant_budget.docx", docx_bytes, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        res_docx = extract_ephemeral_document(uploaded_docx, "consultant_budget.docx")
        assert res_docx["doc_type"] == "docx"
        assert "Consultant travel budget" in res_docx["text"]

        # 2. XLSX
        xlsx_bytes = create_in_memory_xlsx()
        uploaded_xlsx = SimpleUploadedFile("budget_sheet.xlsx", xlsx_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        res_xlsx = extract_ephemeral_document(uploaded_xlsx, "budget_sheet.xlsx")
        assert res_xlsx["doc_type"] == "spreadsheet"
        assert "Airfare" in res_xlsx["text"] or "Expense Item" in res_xlsx["text"]

    def test_proposal_compliance_verdict_supported(self, compliance_fixture):
        """Validates that a proposal adhering to workspace policy returns a compliant verdict."""
        initial_doc_count = SourceDocument.objects.count()
        initial_chunk_count = DocumentChunk.objects.count()

        # Proposal with $60 meal allowance (within $75 policy limit)
        pdf_bytes = create_in_memory_pdf("Travel Grant Proposal\nProposed Daily Meal: $60 per day\nAccommodations: $200 per night.")
        uploaded_pdf = SimpleUploadedFile("travel_request_compliant.pdf", pdf_bytes, content_type="application/pdf")

        user_msg, assistant_msg, envelope = ConversationService.submit_turn(
            conversation=compliance_fixture["conversation"],
            user=compliance_fixture["user"],
            query="Does this travel request comply with company policy?",
            uploaded_file=uploaded_pdf
        )

        assert assistant_msg.status == "completed"
        # Attached document metadata preserved on user turn
        assert user_msg.retrieval_config is not None
        assert "attached_document" in user_msg.retrieval_config
        assert user_msg.retrieval_config["attached_document"]["filename"] == "travel_request_compliant.pdf"

        # Check verdict in synthesized answer
        answer = assistant_msg.content
        assert "VERDICT:" in answer or "POLICY" in answer
        assert "VIOLATION" not in answer.upper()

        # Citations refer to authoritative policy
        assert len(assistant_msg.citations) > 0
        assert any(c.get("document_id") == str(compliance_fixture["policy_doc"].id) for c in assistant_msg.citations)

        # STRICT INVARIANT: Zero DB objects created for the uploaded proposal
        assert SourceDocument.objects.count() == initial_doc_count
        assert DocumentChunk.objects.count() == initial_chunk_count

    def test_proposal_compliance_verdict_violation(self, compliance_fixture):
        """Validates that a proposal exceeding policy allowance is flagged as a violation."""
        initial_doc_count = SourceDocument.objects.count()
        initial_chunk_count = DocumentChunk.objects.count()

        # Proposal with $120 meal allowance (exceeds $75 policy limit)
        pdf_bytes = create_in_memory_pdf("Executive Offsite Proposal\nProposed Daily Meal: $120 per day\nHotel: $300 per night.")
        uploaded_pdf = SimpleUploadedFile("offsite_violation.pdf", pdf_bytes, content_type="application/pdf")

        user_msg, assistant_msg, envelope = ConversationService.submit_turn(
            conversation=compliance_fixture["conversation"],
            user=compliance_fixture["user"],
            query="Review this proposal against company expense limits.",
            uploaded_file=uploaded_pdf
        )

        assert assistant_msg.status == "completed"
        answer = assistant_msg.content

        # Policy violation flagged
        assert "VIOLATION" in answer.upper() or "NOT COMPLIANT" in answer.upper() or assistant_msg.governance_state == "violation"

        # Zero DB objects created for proposal
        assert SourceDocument.objects.count() == initial_doc_count
        assert DocumentChunk.objects.count() == initial_chunk_count

    def test_conversation_messages_view_multipart_upload(self, compliance_fixture):
        """Validates the HTTP POST /api/v1/decisions/conversations/<id>/messages/ with multipart file upload."""
        client = APIClient()
        client.force_authenticate(user=compliance_fixture["user"])

        pdf_bytes = create_in_memory_pdf("Conference Attendance Request\nMeal Per Diem: $55 per day.")
        uploaded_file = SimpleUploadedFile("conference_request.pdf", pdf_bytes, content_type="application/pdf")

        url = f"/api/v1/decisions/conversations/{compliance_fixture['conversation'].id}/messages/"
        response: Any = client.post(
            url,
            {
                "query": "Is this conference attendance within expense guidelines?",
                "file": uploaded_file
            },
            format="multipart"
        )

        assert response.status_code in (200, 202)
        data = response.json()
        assert "user_message" in data
        assert "assistant_message" in data
        assert data["user_message"]["retrieval_config"]["attached_document"]["filename"] == "conference_request.pdf"
        assert "VERDICT:" in data["assistant_message"]["content"] or "POLICY" in data["assistant_message"]["content"]

    def test_governed_query_view_multipart_upload(self, compliance_fixture):
        """Validates the HTTP POST /api/v1/retrieval/query/ endpoint with file upload."""
        client = APIClient()
        client.force_authenticate(user=compliance_fixture["user"])

        pdf_bytes = create_in_memory_pdf("Budget Submission for Marketing Campaign\nEstimated Spend: $5,000")
        uploaded_file = SimpleUploadedFile("marketing_budget.pdf", pdf_bytes, content_type="application/pdf")

        response: Any = client.post(
            "/api/v1/retrieval/query/",
            {
                "workspace": str(compliance_fixture["ws"].id),
                "query": "Does this marketing budget comply with financial governance?",
                "file": uploaded_file,
                "save_conversation": "true"
            },
            format="multipart"
        )

        assert response.status_code == 200
        data = response.json()
        assert "attached_document" in data
        assert data["attached_document"]["filename"] == "marketing_budget.pdf"
        assert "answer" in data
        assert "conversation_id" in data

    def test_unsupported_file_extension_rejected(self, compliance_fixture):
        """Validates that unsafe or unsupported executable file formats are rejected with a 400 error."""
        client = APIClient()
        client.force_authenticate(user=compliance_fixture["user"])

        malicious_file = SimpleUploadedFile("script.exe", b"MZ\x90\x00\x03\x00\x00\x00", content_type="application/octet-stream")
        url = f"/api/v1/decisions/conversations/{compliance_fixture['conversation'].id}/messages/"

        response: Any = client.post(
            url,
            {
                "query": "Check this file",
                "file": malicious_file
            },
            format="multipart"
        )

        assert response.status_code == 400
        assert "Unsupported" in str(response.json()) or "Invalid" in str(response.json())


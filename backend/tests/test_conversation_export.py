import uuid
import pytest
from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework.exceptions import PermissionDenied

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument, DocumentVersion
from apps.knowledge.models import DocumentChunk
from apps.decisions.models import Conversation, ChatMessage
from apps.decisions.services import ConversationService


@pytest.fixture
def export_fixture(db):
    uid = uuid.uuid4().hex[:6]
    user_a = User.objects.create_user(username=f"user_a_{uid}", email=f"a_{uid}@lore.test", password="Password123!")
    user_b = User.objects.create_user(username=f"user_b_{uid}", email=f"b_{uid}@lore.test", password="Password123!")

    org = Organization.objects.create(name=f"Org {uid}", slug=f"org-{uid}")
    OrganizationMembership.objects.create(organization=org, user=user_a, role='member')
    OrganizationMembership.objects.create(organization=org, user=user_b, role='member')

    ws_a = Workspace.objects.create(name=f"Workspace A {uid}", slug=f"ws-a-{uid}", organization=org)
    WorkspaceMembership.objects.create(workspace=ws_a, user=user_a, role='member')

    ws_b = Workspace.objects.create(name=f"Workspace B {uid}", slug=f"ws-b-{uid}", organization=org)
    WorkspaceMembership.objects.create(workspace=ws_b, user=user_b, role='member')

    # Seed an authoritative policy document in Workspace A
    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws_a,
        title="Enterprise Security and Privacy Standard",
        original_filename="security_standard.pdf",
        mime_type="application/pdf",
        file_size=2048,
        file_hash=f"hash_{uid}_22222222222222222222222222222222",
        status="ready",
        authority_level=8,
        current_version_number=1,
        effective_date=timezone.now()
    )
    ver = DocumentVersion.objects.create(document=doc, version_number=1, file_hash=doc.file_hash, is_current=True)
    chunk = DocumentChunk.objects.create(
        organization=org,
        workspace=ws_a,
        document=doc,
        document_version=ver,
        chunk_index=0,
        contextual_header="Security > Data Retention",
        text="Customer biometric data must be encrypted with AES-256 and purged within 30 days.",
        token_count=16,
        page_number=3
    )

    return {
        "user_a": user_a,
        "user_b": user_b,
        "org": org,
        "ws_a": ws_a,
        "ws_b": ws_b,
        "doc": doc,
        "chunk": chunk
    }


@pytest.mark.django_db
class TestConversationExport:

    def test_export_conversation_json_structure(self, export_fixture):
        """
        Validates that conversation export in JSON format contains:
        1. questions (with timestamps, attachments, sequence numbers)
        2. answers (governance state, directive, trace id, status)
        3. layers details (L7, L1, L6, L5, L4, L3, L2, L0, validation signals)
        4. sources (authoritative citations, page numbers, excerpts)
        5. latency to give the answer (per turn and stage breakdown, plus summary metrics)
        """
        ws_a = export_fixture["ws_a"]
        user_a = export_fixture["user_a"]
        doc = export_fixture["doc"]

        # 1. Create multi-turn conversation
        conv = ConversationService.create_conversation(
            workspace=ws_a,
            user=user_a,
            title="Biometric Data Retention Inquiry",
            document_id=str(doc.id)
        )

        # Submit Turn 1
        user_msg1, asst_msg1, env1 = ConversationService.submit_turn(
            conversation=conv,
            user=user_a,
            query="What are the retention and encryption rules for biometric data?",
            document_id=str(doc.id)
        )

        # Submit Turn 2
        user_msg2, asst_msg2, env2 = ConversationService.submit_turn(
            conversation=conv,
            user=user_a,
            query="Who has authorization to request early biometric data purging?",
            document_id=str(doc.id)
        )

        # 2. Export conversation via service
        exported = ConversationService.export_conversation(
            conversation=conv,
            user=user_a,
            export_format='json'
        )

        assert isinstance(exported, dict)
        assert exported["export_version"] == "1.0"
        assert exported["workspace"]["name"] == ws_a.name
        assert exported["conversation"]["id"] == str(conv.id)
        assert exported["conversation"]["title"] == conv.title
        assert exported["conversation"]["total_turns"] == 2

        # Verify summary stats
        summary = exported["conversation"]["summary"]
        assert summary["total_turns"] == 2
        assert "avg_latency_ms" in summary
        assert summary["avg_latency_ms"] > 0
        assert "min_latency_ms" in summary
        assert "max_latency_ms" in summary
        assert summary["total_sources_cited"] >= 1

        # Verify turns
        turns = exported["turns"]
        assert len(turns) == 2

        # Turn 1 Checks
        t1 = turns[0]
        assert t1["turn_number"] == 1
        assert "biometric data" in t1["question"]["content"]
        assert t1["question"]["timestamp"] is not None
        assert t1["answer"]["content"] != ""
        assert t1["answer"]["governance_state"] != ""
        assert t1["answer"]["governance_directive"] != ""
        assert t1["answer"]["trace_id"] != ""

        # Verify latency to give the answer
        assert t1["answer"]["latency_ms"] is not None
        assert t1["answer"]["latency_ms"] > 0
        assert isinstance(t1["answer"]["latency_breakdown_ms"], dict)
        assert "total_ms" in t1["answer"]["latency_breakdown_ms"]

        # Verify layers details
        assert "layers_details" in t1
        layers = t1["layers_details"]
        assert "l7_permission" in layers
        assert "l1_decision_intelligence" in layers
        assert "l6_authority" in layers
        assert "l5_temporal" in layers
        assert "l3_sufficiency" in layers
        assert "l2_answer_state" in layers
        assert "l0_observability" in layers

        # Verify sources
        assert "sources" in t1
        assert len(t1["sources"]) >= 1
        src = t1["sources"][0]
        assert src["document_title"] == doc.title
        assert src["authority_level"] == 8
        assert "passage" in src or "shortest_passage" in src

    def test_export_conversation_markdown_format(self, export_fixture):
        """Validates that export in Markdown produces a formatted audit report."""
        ws_a = export_fixture["ws_a"]
        user_a = export_fixture["user_a"]
        doc = export_fixture["doc"]

        conv = ConversationService.create_conversation(
            workspace=ws_a,
            user=user_a,
            title="Biometric Policy Audit",
            document_id=str(doc.id)
        )

        ConversationService.submit_turn(
            conversation=conv,
            user=user_a,
            query="What is the encryption requirement?",
            document_id=str(doc.id)
        )

        md_output = ConversationService.export_conversation(
            conversation=conv,
            user=user_a,
            export_format='markdown'
        )

        assert isinstance(md_output, str)
        assert "# LORE Governed Conversation Audit Export" in md_output
        assert "Biometric Policy Audit" in md_output
        assert "#### ❓ Question" in md_output
        assert "#### 💡 Governed Answer" in md_output
        assert "#### ⚡ Latency Breakdown" in md_output
        assert "#### 🛡️ Governance Layers Details" in md_output
        assert "#### 📚 Authoritative Sources & Proof Citations" in md_output
        assert "Total Turn Latency" in md_output
        assert "L7 Permission:" in md_output

    def test_export_api_endpoints_and_download(self, export_fixture):
        """Validates the HTTP GET /api/v1/decisions/conversations/<id>/export/ endpoint."""
        ws_a = export_fixture["ws_a"]
        user_a = export_fixture["user_a"]
        user_b = export_fixture["user_b"]
        doc = export_fixture["doc"]

        conv = ConversationService.create_conversation(
            workspace=ws_a,
            user=user_a,
            title="Compliance Test",
            document_id=str(doc.id)
        )

        ConversationService.submit_turn(
            conversation=conv,
            user=user_a,
            query="Is AES-256 mandatory?",
            document_id=str(doc.id)
        )

        client = APIClient()
        client.force_authenticate(user=user_a)

        # 1. Test JSON API Export
        res_json = client.get(f"/api/v1/decisions/conversations/{conv.id}/export/?format=json")
        assert res_json.status_code == 200
        data = res_json.json()
        assert data["conversation"]["id"] == str(conv.id)
        assert len(data["turns"]) == 1
        assert data["turns"][0]["answer"]["latency_ms"] is not None

        # 2. Test Markdown API Export
        res_md = client.get(f"/api/v1/decisions/conversations/{conv.id}/export/?format=markdown")
        assert res_md.status_code == 200
        assert "markdown" in res_md.json()
        assert "# LORE Governed Conversation Audit Export" in res_md.json()["markdown"]

        # 3. Test File Download Header
        res_dl = client.get(f"/api/v1/decisions/conversations/{conv.id}/export/?format=json&download=true")
        assert res_dl.status_code == 200
        assert "attachment;" in res_dl.headers.get("Content-Disposition", "")
        assert res_dl.headers.get("Content-Type", "").startswith("application/json")

        res_md_dl = client.get(f"/api/v1/decisions/conversations/{conv.id}/export/?format=markdown&download=true")
        assert res_md_dl.status_code == 200
        assert "attachment;" in res_md_dl.headers.get("Content-Disposition", "")
        assert res_md_dl.headers.get("Content-Type", "").startswith("text/markdown")

        # 4. Cross-user isolation check: User B cannot export User A's conversation
        client_b = APIClient()
        client_b.force_authenticate(user=user_b)
        res_unauth = client_b.get(f"/api/v1/decisions/conversations/{conv.id}/export/")
        assert res_unauth.status_code == 404 or res_unauth.status_code == 403

    def test_citation_revalidation_in_export(self, export_fixture):
        """Validates that if a cited document is deleted, the export redacts its excerpt."""
        ws_a = export_fixture["ws_a"]
        user_a = export_fixture["user_a"]
        doc = export_fixture["doc"]

        conv = ConversationService.create_conversation(
            workspace=ws_a,
            user=user_a,
            title="Archived Source Test",
            document_id=str(doc.id)
        )

        ConversationService.submit_turn(
            conversation=conv,
            user=user_a,
            query="What are the retention and encryption rules for biometric data?",
            document_id=str(doc.id)
        )

        # Mark source document as deleted
        doc.status = "deleted"
        doc.save(update_fields=["status"])

        # Export should redact the passage
        exported = ConversationService.export_conversation(
            conversation=conv,
            user=user_a,
            export_format='json'
        )

        src = exported["turns"][0]["sources"][0]
        assert src["is_inaccessible"] is True
        assert "archived or removed" in src["passage"]

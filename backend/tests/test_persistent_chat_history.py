import uuid
import pytest
from datetime import datetime
from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.knowledge.models import DocumentChunk
from apps.decisions.models import Conversation, ChatMessage, DecisionRecord
from apps.decisions.services import ConversationService
from apps.decisions.title_generator import generate_conversation_title


@pytest.fixture
def chat_fixture(db):
    uid = uuid.uuid4().hex[:6]
    user_a = User.objects.create_user(username=f"user_a_{uid}", email=f"a_{uid}@lore.test", password="Password123!")
    user_b = User.objects.create_user(username=f"user_b_{uid}", email=f"b_{uid}@lore.test", password="Password123!")

    org = Organization.objects.create(name=f"Org {uid}", slug=f"org-{uid}")
    OrganizationMembership.objects.create(organization=org, user=user_a, role='member')
    OrganizationMembership.objects.create(organization=org, user=user_b, role='member')

    ws_a = Workspace.objects.create(name=f"Workspace A {uid}", slug=f"ws-a-{uid}", organization=org)
    WorkspaceMembership.objects.create(workspace=ws_a, user=user_a, role='member')

    ws_other = Workspace.objects.create(name=f"Workspace Other {uid}", slug=f"ws-other-{uid}", organization=org)
    WorkspaceMembership.objects.create(workspace=ws_other, user=user_b, role='member')

    # Seed an authoritative policy document in Workspace A
    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws_a,
        title="Travel and Expense Policy",
        original_filename="travel_expense.pdf",
        mime_type="application/pdf",
        file_size=1024,
        file_hash=f"hash_{uid}_11111111111111111111111111111111",
        status="ready",
        authority_level=7,
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
        contextual_header="Travel > Meal Allowance",
        text="The approved daily meal allowance is $75 per day with itemized receipts required.",
        token_count=18,
        page_number=1
    )

    return {
        "user_a": user_a,
        "user_b": user_b,
        "org": org,
        "ws_a": ws_a,
        "ws_other": ws_other,
        "doc": doc,
        "chunk": chunk
    }


@pytest.mark.django_db
class TestPersistentChatHistoryBackend:

    def test_deterministic_title_generation(self):
        """Validates that titles are formulated cleanly without hallucination or punctuation."""
        assert generate_conversation_title("What is the travel expense policy?") == "Travel Expense Policy"
        assert generate_conversation_title("Can you explain the procurement approval limits?") == "Procurement Approval Limits"
        assert generate_conversation_title("What access-control actions must be logged?") == "Access-Control Logging"
        assert generate_conversation_title("") == "New Conversation"
        assert generate_conversation_title("   ") == "New Conversation"

    def test_create_and_list_conversations(self, chat_fixture):
        """Validates conversation creation, tenancy, and metadata listing."""
        ws_a = chat_fixture["ws_a"]
        user_a = chat_fixture["user_a"]

        conv1 = ConversationService.create_conversation(workspace=ws_a, user=user_a, title="Initial Inquiry")
        assert conv1.id is not None
        assert conv1.title == "Initial Inquiry"
        assert conv1.workspace == ws_a
        assert conv1.user == user_a
        assert conv1.is_deleted is False

        conv2 = ConversationService.create_conversation(workspace=ws_a, user=user_a, title="Second Topic")
        
        # List conversations
        client = APIClient()
        client.force_authenticate(user=user_a)
        res = client.get(f"/api/v1/decisions/conversations/?workspace={ws_a.id}")
        assert res.status_code == 200
        data = res.json().get("results", res.json())
        assert len(data) == 2
        titles = [c["title"] for c in data]
        assert "Second Topic" in titles
        assert "Initial Inquiry" in titles

    def test_submit_turn_and_message_persistence(self, chat_fixture):
        """Validates full turn execution, user + assistant message persistence, and citations."""
        ws_a = chat_fixture["ws_a"]
        user_a = chat_fixture["user_a"]

        conv = ConversationService.create_conversation(workspace=ws_a, user=user_a, title="New Conversation")
        
        user_msg, asst_msg, envelope = ConversationService.submit_turn(
            conversation=conv,
            user=user_a,
            query="What is the meal allowance?"
        )

        assert user_msg.role == "user"
        assert user_msg.sequence_number == 1
        assert user_msg.content == "What is the meal allowance?"

        assert asst_msg.role == "assistant"
        assert asst_msg.sequence_number == 2
        assert asst_msg.status == "completed"
        assert "$75" in asst_msg.content
        assert asst_msg.governance_state in ("supported", "qualified")
        assert len(asst_msg.citations) >= 1
        assert asst_msg.citations[0]["document_title"] == "Travel and Expense Policy"

        # Auto-title formulation should have updated the default title
        conv.refresh_from_db()
        assert conv.title != "New Conversation"

    def test_continue_conversation_with_multiple_turns(self, chat_fixture):
        """Validates sequential turn numbering and multi-turn message history loading."""
        ws_a = chat_fixture["ws_a"]
        user_a = chat_fixture["user_a"]
        conv = ConversationService.create_conversation(workspace=ws_a, user=user_a)

        # Turn 1
        ConversationService.submit_turn(conversation=conv, user=user_a, query="What is the meal allowance?")
        
        # Turn 2
        ConversationService.submit_turn(conversation=conv, user=user_a, query="Are receipts required?")

        conv.refresh_from_db()
        messages = list(conv.messages.order_by('sequence_number'))
        assert len(messages) == 4
        assert [m.role for m in messages] == ['user', 'assistant', 'user', 'assistant']
        assert [m.sequence_number for m in messages] == [1, 2, 3, 4]

        # Verify API detail loads messages chronologically
        client = APIClient()
        client.force_authenticate(user=user_a)
        res = client.get(f"/api/v1/decisions/conversations/{conv.id}/")
        assert res.status_code == 200
        detail = res.json()
        assert len(detail["messages"]) == 4
        assert detail["messages"][0]["sequence_number"] == 1
        assert detail["messages"][3]["sequence_number"] == 4

    def test_idempotent_duplicate_prevention(self, chat_fixture):
        """Validates that duplicate requests with identical client_message_id return existing turns."""
        ws_a = chat_fixture["ws_a"]
        user_a = chat_fixture["user_a"]
        conv = ConversationService.create_conversation(workspace=ws_a, user=user_a)

        client_msg_id = "client-uuid-999-doubleclick"

        # First submit
        u1, a1, env1 = ConversationService.submit_turn(
            conversation=conv,
            user=user_a,
            query="What is the meal allowance?",
            client_message_id=client_msg_id
        )

        # Immediate retry with same client_message_id
        u2, a2, env2 = ConversationService.submit_turn(
            conversation=conv,
            user=user_a,
            query="What is the meal allowance?",
            client_message_id=client_msg_id
        )

        assert u1.id == u2.id
        assert a1.id == a2.id
        assert conv.messages.count() == 2

    def test_cross_user_and_cross_workspace_isolation(self, chat_fixture):
        """Enforces that User B cannot read, rename, or message User A's private conversation."""
        ws_a = chat_fixture["ws_a"]
        user_a = chat_fixture["user_a"]
        user_b = chat_fixture["user_b"]

        conv_a = ConversationService.create_conversation(workspace=ws_a, user=user_a, title="User A Confidential")

        client_b = APIClient()
        client_b.force_authenticate(user=user_b)

        # 1. User B cannot list User A's conversation
        res_list = client_b.get(f"/api/v1/decisions/conversations/?workspace={ws_a.id}")
        assert res_list.status_code == 200
        data_b = res_list.json().get("results", res_list.json())
        assert len(data_b) == 0

        # 2. User B cannot retrieve User A's conversation details
        res_get = client_b.get(f"/api/v1/decisions/conversations/{conv_a.id}/")
        assert res_get.status_code == 404

        # 3. User B cannot rename User A's conversation
        res_patch = client_b.patch(f"/api/v1/decisions/conversations/{conv_a.id}/", {"title": "Hacked Title"})
        assert res_patch.status_code == 404

        # 4. User B cannot send messages to User A's conversation
        res_msg = client_b.post(f"/api/v1/decisions/conversations/{conv_a.id}/messages/", {"query": "Malicious probe"})
        assert res_msg.status_code == 404

    def test_rename_and_soft_delete(self, chat_fixture):
        """Validates renaming conversation and soft-deletion lifecycle."""
        ws_a = chat_fixture["ws_a"]
        user_a = chat_fixture["user_a"]
        conv = ConversationService.create_conversation(workspace=ws_a, user=user_a, title="Old Title")

        client = APIClient()
        client.force_authenticate(user=user_a)

        # Rename
        res_rename = client.patch(f"/api/v1/decisions/conversations/{conv.id}/", {"title": "Renamed Policy Discussion"})
        assert res_rename.status_code == 200
        assert res_rename.json()["title"] == "Renamed Policy Discussion"

        # Soft delete
        res_del = client.delete(f"/api/v1/decisions/conversations/{conv.id}/")
        assert res_del.status_code == 200
        conv.refresh_from_db()
        assert conv.is_deleted is True

        # Deleted conversation no longer in active list
        res_list = client.get(f"/api/v1/decisions/conversations/?workspace={ws_a.id}")
        data_del = res_list.json().get("results", res_list.json())
        assert len(data_del) == 0

    def test_citation_revalidation_when_document_deleted(self, chat_fixture):
        """Validates that passages are redacted if a cited document was subsequently deleted."""
        ws_a = chat_fixture["ws_a"]
        user_a = chat_fixture["user_a"]
        doc = chat_fixture["doc"]
        conv = ConversationService.create_conversation(workspace=ws_a, user=user_a)

        ConversationService.submit_turn(conversation=conv, user=user_a, query="What is the meal allowance?")
        
        # Soft-delete the document
        doc.status = "deleted"
        doc.save()

        client = APIClient()
        client.force_authenticate(user=user_a)
        res = client.get(f"/api/v1/decisions/conversations/{conv.id}/")
        assert res.status_code == 200
        messages = res.json()["messages"]
        asst = [m for m in messages if m["role"] == "assistant"][0]
        
        # Revalidated citations must redact removed document passages
        reval_cits = asst["revalidated_citations"]
        assert len(reval_cits) >= 1
        assert "removed" in reval_cits[0]["passage"].lower() or "archived" in reval_cits[0]["passage"].lower()
        assert reval_cits[0].get("is_inaccessible") is True

    def test_search_conversations(self, chat_fixture):
        """Validates searching conversations by title or message content."""
        ws_a = chat_fixture["ws_a"]
        user_a = chat_fixture["user_a"]

        conv1 = ConversationService.create_conversation(workspace=ws_a, user=user_a, title="Travel Policy QA")
        ConversationService.submit_turn(conversation=conv1, user=user_a, query="What is the meal allowance?")

        conv2 = ConversationService.create_conversation(workspace=ws_a, user=user_a, title="Security Guidelines")
        ConversationService.submit_turn(conversation=conv2, user=user_a, query="What are the firewall rules?")

        client = APIClient()
        client.force_authenticate(user=user_a)

        # Search title
        res_t = client.get(f"/api/v1/decisions/conversations/?workspace={ws_a.id}&search=Travel")
        data_t = res_t.json().get("results", res_t.json())
        assert len(data_t) == 1
        assert data_t[0]["id"] == str(conv1.id)

        # Search message content
        res_c = client.get(f"/api/v1/decisions/conversations/?workspace={ws_a.id}&search=firewall")
        data_c = res_c.json().get("results", res_c.json())
        assert len(data_c) == 1
        assert data_c[0]["id"] == str(conv2.id)

    def test_governed_query_endpoint_persists_turn(self, chat_fixture):
        """Validates that POST /api/v1/retrieval/query/ seamlessly persists to conversation."""
        ws_a = chat_fixture["ws_a"]
        user_a = chat_fixture["user_a"]

        client = APIClient()
        client.force_authenticate(user=user_a)

        res = client.post("/api/v1/retrieval/query/", {
            "workspace": str(ws_a.id),
            "query": "What is the meal allowance?",
            "save_conversation": True
        }, format="json")

        assert res.status_code == 200
        data = res.json()
        assert "conversation_id" in data
        assert "user_message_id" in data
        assert "assistant_message_id" in data

        conv = Conversation.objects.get(id=data["conversation_id"])
        assert conv.messages.count() == 2

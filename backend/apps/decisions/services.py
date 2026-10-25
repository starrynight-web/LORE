import logging
from typing import Optional, Dict, Any, Tuple
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument
from apps.retrieval.services import HybridRetrievalService
from apps.governance.layers import EnterpriseGovernanceEngine, PermissionLayer
from apps.governance.contract import fail_closed_envelope
from apps.audit.models import AuditEvent
from .models import Conversation, ChatMessage, DecisionRecord
from .title_generator import generate_conversation_title

logger = logging.getLogger(__name__)


class ConversationService:
    """
    Enterprise Conversation & Persistent Turn Management for LORE's Governed RAG.
    Enforces workspace isolation, user tenancy, idempotency, bounded multi-turn context,
    and automatic deterministic title formulation.
    """

    @classmethod
    def verify_workspace_access(cls, workspace: Workspace, user: User) -> Optional[WorkspaceMembership]:
        """Verifies that the user has an active membership in the workspace."""
        membership = WorkspaceMembership.objects.filter(workspace=workspace, user=user).first()
        if not membership and not user.is_staff:
            raise PermissionDenied(f"User '{user.username}' is not a member of workspace '{workspace.name}'.")
        return membership

    @classmethod
    def create_conversation(
        cls,
        workspace: Workspace,
        user: User,
        title: Optional[str] = None,
        document_id: Optional[str] = None,
        collection_id: Optional[str] = None
    ) -> Conversation:
        """Creates a new persistent conversation thread scoped to the workspace and user."""
        cls.verify_workspace_access(workspace, user)

        doc = None
        if document_id:
            doc = SourceDocument.objects.filter(id=document_id, workspace=workspace).first()

        clean_title = (title or "New Conversation").strip()
        if len(clean_title) > 255:
            clean_title = clean_title[:250] + "..."

        conversation = Conversation.objects.create(
            organization=workspace.organization,
            workspace=workspace,
            user=user,
            title=clean_title,
            document=doc,
            collection_id=collection_id
        )

        AuditEvent.objects.create(
            organization=workspace.organization,
            workspace=workspace,
            user=user,
            event_type='retrieval_query',
            target_type='conversation',
            target_id=str(conversation.id),
            details={'action': 'conversation_created', 'title': clean_title}
        )

        return conversation

    @classmethod
    def revalidate_citations(cls, citations: list, user: User, workspace: Workspace) -> list:
        """
        Revalidates access to documents cited in past turns.
        If a document was deleted or access was revoked since the turn was saved,
        redacts its content to avoid leaking protected or deleted documents (Requirement 6 & 7).
        """
        if not citations:
            return []

        doc_ids = [c.get('document_id') for c in citations if c.get('document_id')]
        existing_docs = {
            str(d.id): d
            for d in SourceDocument.objects.filter(id__in=doc_ids, workspace=workspace)
        }

        user_role = 'workspace_admin' if getattr(user, 'is_staff', False) else 'member'
        revalidated = []

        for cit in citations:
            c = dict(cit)
            did = str(c.get('document_id') or '')
            doc = existing_docs.get(did)

            if not doc or doc.status in ('deleted', 'quarantined', 'failed'):
                c['passage'] = "[Authoritative reference document has been archived or removed]"
                c['shortest_passage'] = "[Removed]"
                c['is_inaccessible'] = True
            elif not PermissionLayer.can_access_document(doc, user, user_role):
                c['passage'] = "[Protected document — Access restricted for current user]"
                c['shortest_passage'] = "[Restricted]"
                c['is_inaccessible'] = True
            revalidated.append(c)

        return revalidated

    @classmethod
    def submit_turn(
        cls,
        conversation: Conversation,
        user: User,
        query: str,
        client_message_id: Optional[str] = None,
        document_id: Optional[str] = None,
        collection_id: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        llm_model: Optional[str] = None,
        execution_mode: Optional[str] = None,
        synthesis_mode: Optional[str] = None,
        as_of: Optional[Any] = None
    ) -> Tuple[ChatMessage, ChatMessage, Dict[str, Any]]:
        """
        Executes a complete chat turn in a persistent conversation:
        1. Checks idempotency to prevent duplicate submissions on double-clicks / retries.
        2. Persists the user question.
        3. Updates conversation title if first turn.
        4. Runs governed search & RAG with bounded conversational context.
        5. Persists the assistant's governed response with structured citations.
        6. On failure, preserves the user question with a clear failed status.
        """
        clean_query = query.strip()
        if not clean_query:
            raise ValidationError("Query cannot be empty.")

        # Tenancy check
        if conversation.user_id != user.id and not user.is_staff:
            raise PermissionDenied("Access to this conversation is denied.")
        if conversation.is_deleted:
            raise ValidationError("Cannot post to a deleted conversation.")

        cls.verify_workspace_access(conversation.workspace, user)

        # Idempotency control: return existing turn if client_message_id already exists
        if client_message_id:
            existing_user_msg = ChatMessage.objects.filter(
                conversation=conversation,
                client_message_id=client_message_id
            ).first()
            if existing_user_msg:
                # Find matching assistant message
                existing_assistant_msg = ChatMessage.objects.filter(
                    conversation=conversation,
                    sequence_number=existing_user_msg.sequence_number + 1,
                    role='assistant'
                ).first()
                if existing_assistant_msg:
                    logger.info(f"[Conversation] Idempotent hit for client_message_id={client_message_id}")
                    # Reconstruct envelope
                    cached_envelope = {
                        'schema': 'lore.result/2',
                        'state': existing_assistant_msg.governance_state,
                        'directive': existing_assistant_msg.governance_directive,
                        'answer': existing_assistant_msg.content,
                        'citations': existing_assistant_msg.citations,
                        'evidence_missing': existing_assistant_msg.evidence_missing,
                        'conflicts_resolved': existing_assistant_msg.conflicts_resolved,
                        'layers_breakdown': existing_assistant_msg.layers_breakdown,
                        'trace_id': existing_assistant_msg.trace_id,
                        'cached': True,
                    }
                    return existing_user_msg, existing_assistant_msg, cached_envelope

        # Determine next sequence numbers
        with transaction.atomic():
            last_msg = conversation.messages.order_by('-sequence_number').first()
            next_seq = (last_msg.sequence_number + 1) if last_msg else 1

            # 1. Persist User Question
            user_msg = ChatMessage.objects.create(
                conversation=conversation,
                role='user',
                content=clean_query,
                sequence_number=next_seq,
                status='completed',
                client_message_id=client_message_id or ''
            )

            # Auto-title conversation on first turn if untitled or default
            if conversation.title in ("New Conversation", "Governed Inquiry", ""):
                new_title = generate_conversation_title(clean_query)
                conversation.title = new_title
                conversation.save(update_fields=['title', 'updated_at'])

        # 2. Extract Bounded Conversation Context (Requirement 6: max 4 recent turns / 8 messages)
        # Prior turns provide context but NEVER override source evidence or become policy
        recent_turns = list(
            conversation.messages.exclude(id=user_msg.id)
            .order_by('-sequence_number')[:6]
        )
        recent_turns.reverse()

        conversation_history_summary = []
        for turn in recent_turns:
            conversation_history_summary.append({
                'role': turn.role,
                'content': turn.content[:300], # Bounded content to avoid prompt exhaustion
                'state': turn.governance_state,
            })

        effective_doc_id = document_id or (str(conversation.document.id) if conversation.document else None)
        effective_col_id = collection_id or (str(conversation.collection.id) if conversation.collection else None)
        user_role = 'workspace_admin' if getattr(user, 'is_staff', False) else 'member'

        # 3. Execute Governed Retrieval Pipeline
        retrieval_service = HybridRetrievalService()
        envelope = None
        assistant_msg = None

        try:
            candidate_chunks = retrieval_service.search(
                query=clean_query,
                workspace_id=str(conversation.workspace_id),
                organization_id=str(conversation.organization_id),
                collection_id=effective_col_id,
                document_id=effective_doc_id,
                limit=10,
                user=user,
                user_role=user_role,
                as_of=as_of
            )

            policy_ctx = {
                'conversation_id': str(conversation.id),
                'conversation_history': conversation_history_summary,
                'is_multi_turn': len(conversation_history_summary) > 0,
            }

            envelope = EnterpriseGovernanceEngine.evaluate(
                query=clean_query,
                retrieved_chunks=candidate_chunks,
                workspace=conversation.workspace,
                user=user,
                user_role=user_role,
                as_of=as_of,
                schema_version='lore.result/2',
                groq_api_key=groq_api_key,
                llm_model=llm_model,
                execution_mode=execution_mode,
                synthesis_mode=synthesis_mode,
                policy_context=policy_ctx
            )

            # Persist DecisionRecord for audit lineage
            with transaction.atomic():
                decision_rec = DecisionRecord.objects.create(
                    trace_id=envelope.get('trace_id') or f"trace-{conversation.id.hex[:8]}",
                    organization=conversation.organization,
                    workspace=conversation.workspace,
                    user=user,
                    query=clean_query,
                    decision_type=envelope.get('decision_type', 'general_inquiry'),
                    state=envelope.get('state', 'supported'),
                    directive=envelope.get('directive', 'proceed_and_cite'),
                    answer_text=envelope.get('answer', ''),
                    evidence_found=envelope.get('evidence_found', []),
                    evidence_missing=envelope.get('evidence_missing', []),
                    conflicts_resolved=envelope.get('conflicts_resolved', []),
                    citations=envelope.get('citations', []),
                    token_count=envelope.get('token_count', 0)
                )

                # Persist Assistant Response
                assistant_msg = ChatMessage.objects.create(
                    conversation=conversation,
                    role='assistant',
                    content=envelope.get('answer', ''),
                    sequence_number=next_seq + 1,
                    status='completed',
                    decision=decision_rec,
                    governance_state=envelope.get('state', ''),
                    governance_directive=envelope.get('directive', ''),
                    trace_id=envelope.get('trace_id', ''),
                    citations=envelope.get('citations', []),
                    evidence_missing=envelope.get('evidence_missing', []),
                    conflicts_resolved=envelope.get('conflicts_resolved', []),
                    layers_breakdown=envelope.get('layers_breakdown', {}),
                    retrieval_config={
                        'document_id': effective_doc_id,
                        'collection_id': effective_col_id,
                        'llm_model': llm_model or 'gpt-oss-120B',
                        'execution_mode': execution_mode
                    }
                )

                conversation.last_activity_at = timezone.now()
                conversation.save(update_fields=['last_activity_at', 'updated_at'])

            # Log audit event
            AuditEvent.objects.create(
                organization=conversation.organization,
                workspace=conversation.workspace,
                user=user,
                event_type='decision_recorded',
                target_type='conversation_turn',
                target_id=str(assistant_msg.id),
                details={
                    'conversation_id': str(conversation.id),
                    'state': envelope.get('state'),
                    'directive': envelope.get('directive'),
                    'citations_count': len(envelope.get('citations', []))
                }
            )

        except Exception as ex:
            logger.exception(f"[Conversation] Turn execution failed: {ex}")
            fail_env = fail_closed_envelope(
                query=clean_query,
                error_message=f"Governed answer generation failed: {ex}",
                error_category="GOVERNANCE_EXECUTION_FAILURE"
            )

            # Preserve user question; record failed assistant turn
            with transaction.atomic():
                assistant_msg = ChatMessage.objects.create(
                    conversation=conversation,
                    role='assistant',
                    content=fail_env.get('answer', 'The governance engine was unable to synthesize an authoritative answer.'),
                    sequence_number=next_seq + 1,
                    status='failed',
                    governance_state=fail_env.get('state', 'insufficient'),
                    governance_directive=fail_env.get('directive', 'stop'),
                    error_message=str(ex),
                    retrieval_config={'error': str(ex)}
                )
                conversation.last_activity_at = timezone.now()
                conversation.save(update_fields=['last_activity_at', 'updated_at'])

            envelope = fail_env

        return user_msg, assistant_msg, envelope

import time
import logging
from typing import Optional, Dict, Any, Tuple, Union, List
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
        as_of: Optional[Any] = None,
        uploaded_file: Optional[Any] = None
    ) -> Tuple[ChatMessage, ChatMessage, Dict[str, Any]]:
        """
        Executes a complete chat turn in a persistent conversation:
        1. Checks idempotency to prevent duplicate submissions on double-clicks / retries.
        2. Optionally processes an ephemeral attached document (PDF, DOCX, XLSX, image)
           with full OCR & visual extraction without storing it in the vector database.
        3. Persists the user question and attached document metadata.
        4. Updates conversation title if first turn.
        5. Runs governed search & RAG with bounded conversational context.
        6. Persists the assistant's governed response with structured citations.
        7. On failure, preserves the user question with a clear failed status.
        """
        clean_query = (query or '').strip()

        # Handle optional ephemeral document upload (never saved to vector DB)
        ephemeral_doc = None
        user_retrieval_config: Dict[str, Any] = {}
        if uploaded_file:
            from apps.ingestion.pipeline.ephemeral import extract_ephemeral_document
            try:
                ephemeral_doc = extract_ephemeral_document(uploaded_file)
            except Exception as err:
                raise ValidationError(f"Invalid attachment: {err}")
            user_retrieval_config['attached_document'] = {
                'filename': ephemeral_doc['filename'],
                'file_size': ephemeral_doc['file_size'],
                'doc_type': ephemeral_doc['doc_type'],
                'pages_count': ephemeral_doc['pages_count'],
                'word_count': ephemeral_doc['word_count'],
                'summary': ephemeral_doc['summary'],
            }
            if not clean_query:
                clean_query = f"Review uploaded proposal '{ephemeral_doc['filename']}' against company policy."

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
                client_message_id=client_message_id or '',
                retrieval_config=user_retrieval_config
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
        t_turn_start = time.time()

        try:
            search_query = clean_query
            if ephemeral_doc and ephemeral_doc.get('text'):
                snippet = " ".join(ephemeral_doc['text'].split()[:30])
                search_query = f"{clean_query} {snippet}".strip()

            candidate_chunks = retrieval_service.multi_hop_search(
                query=search_query,
                workspace_id=str(conversation.workspace_id),
                organization_id=str(conversation.organization_id),
                collection_id=effective_col_id,
                document_id=effective_doc_id,
                limit=12,
                user=user,
                user_role=user_role,
                as_of=as_of,
                enable_multi_hop=True
            )

            policy_ctx = {
                'conversation_id': str(conversation.id),
                'conversation_history': conversation_history_summary,
                'is_multi_turn': len(conversation_history_summary) > 0,
                'ephemeral_document': ephemeral_doc,
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

            turn_latency_ms = max(0.1, round((time.time() - t_turn_start) * 1000, 2))
            if isinstance(envelope, dict):
                if 'layers_breakdown' in envelope and isinstance(envelope['layers_breakdown'], dict):
                    l0 = envelope['layers_breakdown'].setdefault('l0_observability', {})
                    timings = l0.setdefault('timings_ms', {})
                    if 'total_ms' not in timings or not timings['total_ms']:
                        timings['total_ms'] = turn_latency_ms

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
                        'execution_mode': execution_mode,
                        'latency_ms': turn_latency_ms,
                        'validation_signals': envelope.get('validation_signals', {}) if isinstance(envelope, dict) else {},
                        'attached_document': user_retrieval_config.get('attached_document')
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
            fail_latency_ms = max(0.1, round((time.time() - t_turn_start) * 1000, 2))
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
                    retrieval_config={'error': str(ex), 'latency_ms': fail_latency_ms}
                )
                conversation.last_activity_at = timezone.now()
                conversation.save(update_fields=['last_activity_at', 'updated_at'])

            envelope = fail_env

        return user_msg, assistant_msg, envelope

    @classmethod
    def export_conversation(
        cls,
        conversation: Conversation,
        user: User,
        export_format: str = 'json'
    ) -> Union[Dict[str, Any], str]:
        """
        Exports a full persistent conversation audit trail including:
        - The questions (with timestamps, sequence numbers, and attachments)
        - The answers (governance state, directive, status, trace ID, decision ID)
        - The layers details (full 8/9-layer governance ledger: L7, L1, L6, L5, L4, L3, L2, L0, Graph)
        - The authoritative sources and citations (dynamically revalidated for tenant access)
        - The latency to give the answer (per turn and stage breakdown, plus summary metrics)
        """
        if conversation.user_id != user.id and not user.is_staff:
            raise PermissionDenied("Access to this conversation is denied.")
        if conversation.is_deleted:
            raise ValidationError("Cannot export a deleted conversation.")

        cls.verify_workspace_access(conversation.workspace, user)

        # Retrieve messages ordered chronologically
        messages = list(conversation.messages.order_by('sequence_number', 'created_at'))

        turns: List[Dict[str, Any]] = []
        pending_user_msg: Optional[ChatMessage] = None
        turn_counter = 1

        for msg in messages:
            if msg.role == 'user':
                if pending_user_msg is not None:
                    # User asked two questions without assistant turn in between
                    turns.append(cls._format_turn_dict(
                        turn_number=turn_counter,
                        user_msg=pending_user_msg,
                        asst_msg=None,
                        user=user,
                        workspace=conversation.workspace
                    ))
                    turn_counter += 1
                pending_user_msg = msg
            elif msg.role == 'assistant':
                turns.append(cls._format_turn_dict(
                    turn_number=turn_counter,
                    user_msg=pending_user_msg,
                    asst_msg=msg,
                    user=user,
                    workspace=conversation.workspace
                ))
                turn_counter += 1
                pending_user_msg = None
            else:
                # System or other messages
                pass

        if pending_user_msg is not None:
            turns.append(cls._format_turn_dict(
                turn_number=turn_counter,
                user_msg=pending_user_msg,
                asst_msg=None,
                user=user,
                workspace=conversation.workspace
            ))

        # Calculate conversation-level latency and summary statistics
        valid_latencies = [
            t['answer']['latency_ms']
            for t in turns
            if t['answer'] and t['answer'].get('latency_ms') is not None
        ]
        avg_latency_ms = round(sum(valid_latencies) / len(valid_latencies), 2) if valid_latencies else 0.0
        min_latency_ms = min(valid_latencies) if valid_latencies else 0.0
        max_latency_ms = max(valid_latencies) if valid_latencies else 0.0
        total_sources_count = sum(len(t.get('sources', [])) for t in turns)

        gov_states_distribution: Dict[str, int] = {}
        for t in turns:
            st = t.get('answer', {}).get('governance_state')
            if st:
                gov_states_distribution[st] = gov_states_distribution.get(st, 0) + 1

        export_dict: Dict[str, Any] = {
            "export_version": "1.0",
            "exported_at": timezone.now().isoformat(),
            "workspace": {
                "id": str(conversation.workspace_id),
                "name": conversation.workspace.name,
                "organization": conversation.organization.name if conversation.organization else "",
            },
            "conversation": {
                "id": str(conversation.id),
                "title": conversation.title,
                "user": conversation.user.username,
                "created_at": conversation.created_at.isoformat() if conversation.created_at else "",
                "last_activity_at": conversation.last_activity_at.isoformat() if conversation.last_activity_at else "",
                "total_turns": len(turns),
                "summary": {
                    "total_turns": len(turns),
                    "total_sources_cited": total_sources_count,
                    "avg_latency_ms": avg_latency_ms,
                    "min_latency_ms": min_latency_ms,
                    "max_latency_ms": max_latency_ms,
                    "governance_states": gov_states_distribution
                }
            },
            "turns": turns
        }

        # Log audit event
        AuditEvent.objects.create(
            organization=conversation.organization,
            workspace=conversation.workspace,
            user=user,
            event_type='retrieval_query',
            target_type='conversation_export',
            target_id=str(conversation.id),
            details={
                'action': 'conversation_exported',
                'format': export_format,
                'title': conversation.title,
                'turns_count': len(turns)
            }
        )

        if export_format in ('markdown', 'md'):
            return cls._render_markdown_export(export_dict)

        return export_dict

    @classmethod
    def _format_turn_dict(
        cls,
        turn_number: int,
        user_msg: Optional[ChatMessage],
        asst_msg: Optional[ChatMessage],
        user: User,
        workspace: Workspace
    ) -> Dict[str, Any]:
        # Latency calculation
        latency_ms = None
        latency_breakdown: Dict[str, Any] = {}

        if asst_msg:
            lb = asst_msg.layers_breakdown or {}
            l0 = lb.get('l0_observability') or {}
            timings = l0.get('timings_ms') or {}
            if isinstance(timings, dict):
                latency_breakdown = dict(timings)
                latency_ms = timings.get('total_ms')

            if latency_ms is None and asst_msg.retrieval_config:
                latency_ms = asst_msg.retrieval_config.get('latency_ms')

            if latency_ms is None and user_msg and asst_msg.created_at and user_msg.created_at:
                diff_ms = max(0.1, (asst_msg.created_at - user_msg.created_at).total_seconds() * 1000)
                latency_ms = round(diff_ms, 2)
                if 'total_ms' not in latency_breakdown:
                    latency_breakdown['total_ms'] = latency_ms

        # Layers details
        layers_details: Dict[str, Any] = {}
        if asst_msg and asst_msg.layers_breakdown:
            layers_details = dict(asst_msg.layers_breakdown)
        if asst_msg:
            if asst_msg.evidence_missing:
                layers_details['evidence_missing'] = asst_msg.evidence_missing
            if asst_msg.conflicts_resolved:
                layers_details['conflicts_resolved'] = asst_msg.conflicts_resolved
            if asst_msg.retrieval_config and asst_msg.retrieval_config.get('validation_signals'):
                layers_details['validation_signals'] = asst_msg.retrieval_config['validation_signals']

        # Revalidated sources
        revalidated_sources: List[Dict[str, Any]] = []
        if asst_msg and asst_msg.citations:
            revalidated_sources = cls.revalidate_citations(
                asst_msg.citations,
                user=user,
                workspace=workspace
            )

        return {
            "turn_number": turn_number,
            "question": {
                "id": str(user_msg.id) if user_msg else None,
                "content": user_msg.content if user_msg else "",
                "timestamp": user_msg.created_at.isoformat() if user_msg else None,
                "sequence_number": user_msg.sequence_number if user_msg else None,
                "attached_document": user_msg.retrieval_config.get('attached_document') if (user_msg and user_msg.retrieval_config) else None
            },
            "answer": {
                "id": str(asst_msg.id) if asst_msg else None,
                "content": asst_msg.content if asst_msg else "",
                "governance_state": asst_msg.governance_state if asst_msg else "unknown",
                "governance_directive": asst_msg.governance_directive if asst_msg else "unknown",
                "status": asst_msg.status if asst_msg else "unknown",
                "trace_id": asst_msg.trace_id if asst_msg else "",
                "decision_id": str(asst_msg.decision_id) if (asst_msg and asst_msg.decision_id) else None,
                "error_message": asst_msg.error_message if (asst_msg and asst_msg.error_message) else None,
                "timestamp": asst_msg.created_at.isoformat() if asst_msg else None,
                "sequence_number": asst_msg.sequence_number if asst_msg else None,
                "latency_ms": latency_ms,
                "latency_breakdown_ms": latency_breakdown
            },
            "layers_details": layers_details,
            "sources": revalidated_sources
        }

    @classmethod
    def _render_markdown_export(cls, data: Dict[str, Any]) -> str:
        conv = data.get('conversation', {})
        ws = data.get('workspace', {})
        summary = conv.get('summary', {})
        turns = data.get('turns', [])

        lines = [
            "# LORE Governed Conversation Audit Export",
            "",
            "| Metric / Property | Details |",
            "| :--- | :--- |",
            f"| **Conversation Title** | **{conv.get('title', 'Untitled')}** |",
            f"| **Conversation ID** | `{conv.get('id', '')}` |",
            f"| **Workspace** | {ws.get('name', '')} (`{ws.get('id', '')}`) |",
            f"| **Organization** | {ws.get('organization', '')} |",
            f"| **User** | `{conv.get('user', '')}` |",
            f"| **Export Timestamp** | {data.get('exported_at', '')} |",
            f"| **Total Turns** | {summary.get('total_turns', len(turns))} |",
            f"| **Average Latency** | **{summary.get('avg_latency_ms', 0)} ms** |",
            f"| **Total Sources Cited** | {summary.get('total_sources_cited', 0)} |",
            "",
            "---",
            "",
            "## Conversation Turns",
            ""
        ]

        for turn in turns:
            t_num = turn.get('turn_number', 1)
            q = turn.get('question', {})
            a = turn.get('answer', {})
            layers = turn.get('layers_details', {})
            sources = turn.get('sources', [])
            lat_ms = a.get('latency_ms')
            lat_str = f"{lat_ms:.1f} ms" if isinstance(lat_ms, (int, float)) else "N/A"
            lat_breakdown = a.get('latency_breakdown_ms', {})

            lines.extend([
                f"### Turn {t_num}",
                "",
                "#### ❓ Question",
                f"> {q.get('content', '')}",
                "",
                f"- **Sequence:** Turn {t_num} (Seq #{q.get('sequence_number', t_num)})",
                f"- **Timestamp:** {q.get('timestamp', 'N/A')}",
            ])

            if q.get('attached_document'):
                att = q['attached_document']
                lines.append(f"- **Attached Ephemeral Document:** `{att.get('filename')}` ({att.get('doc_type')}, {(att.get('file_size', 0)/1024):.1f} KB)")

            lines.extend([
                "",
                "#### 💡 Governed Answer",
                f"{a.get('content', '')}",
                "",
                f"- **Governance State:** `{a.get('governance_state', '').upper()}`",
                f"- **Governance Directive:** `{a.get('governance_directive', '').upper()}`",
                f"- **Status:** `{a.get('status', '').upper()}`",
                f"- **Answer Latency:** **{lat_str}**",
            ])

            if a.get('trace_id'):
                lines.append(f"- **Trace ID:** `{a.get('trace_id')}`")
            if a.get('error_message'):
                lines.append(f"- **Error:** `{a.get('error_message')}`")

            # Latency Breakdown
            lines.extend([
                "",
                "#### ⚡ Latency Breakdown",
                "| Pipeline Stage | Latency |",
                "| :--- | :--- |"
            ])
            if lat_breakdown:
                stage_labels = {
                    'l7_permission_ms': 'L7 Permission Check',
                    'l1_intelligence_ms': 'L1 Decision Intelligence',
                    'l5_temporal_ms': 'L5 Temporal Validity',
                    'l4_exception_ms': 'L4 Exceptions Evaluation',
                    'l6_authority_ms': 'L6 Authority & Conflict Resolution',
                    'l3_sufficiency_ms': 'L3 Evidence Sufficiency',
                    'evidence_assembly_ms': 'Evidence Assembly',
                    'generation_ms': 'Deterministic Synthesis / Generation',
                    'validation_ms': 'Answer Quality Validation',
                    'total_ms': 'Total Turn Latency'
                }
                for k, label in stage_labels.items():
                    if k in lat_breakdown and lat_breakdown[k] is not None:
                        val = lat_breakdown[k]
                        bold = "**" if k == 'total_ms' else ""
                        lines.append(f"| {label} | {bold}{val:.2f} ms{bold} |")
            else:
                lines.append(f"| Total Turn Latency | **{lat_str}** |")

            # Governance Layers Details
            lines.extend([
                "",
                "#### 🛡️ Governance Layers Details",
            ])
            l7 = layers.get('l7_permission', {})
            l1 = layers.get('l1_decision_intelligence', {})
            l6 = layers.get('l6_authority', {})
            l5 = layers.get('l5_temporal', {})
            l4 = layers.get('l4_exceptions', {})
            l3 = layers.get('l3_sufficiency', {})
            l2 = layers.get('l2_answer_state', {})
            l0 = layers.get('l0_observability', {})

            lines.append(f"- **L7 Permission:** `{l7.get('status', 'PASSED').upper()}` (Denials: {len(l7.get('denials', []))})")
            lines.append(f"- **L1 Decision Intelligence:** Type: `{l1.get('decision_type', 'general_inquiry')}`, Risk: `{l1.get('risk', 'low')}`, Intent: `{l1.get('query_intent', 'informational')}`")
            lines.append(f"- **L6 Authority:** Conflicts Resolved: {l6.get('conflicts_count', 0)}, Unresolved Tie: {l6.get('unresolved_tie', False)}")
            lines.append(f"- **L5 Temporal Validity:** Stale Data: {l5.get('stale_data', False)}, As Of: {l5.get('as_of') or 'Current'}")
            lines.append(f"- **L4 Exceptions:** Applied Count: {l4.get('applied_count', 0)}")
            lines.append(f"- **L3 Evidence Sufficiency:** Sufficient: {l3.get('is_sufficient', True)}, Missing Requirements: {l3.get('missing_count', 0)}")
            lines.append(f"- **L2 Answer State:** Final State: `{l2.get('final_state', a.get('governance_state', ''))}` • Directive: `{l2.get('directive', a.get('governance_directive', ''))}`")
            lines.append(f"- **L0 Observability:** Immutable Audit Recorded (Trace `{l0.get('trace_id') or a.get('trace_id')}`)")

            # Sources & Proof Citations
            lines.extend([
                "",
                f"#### 📚 Authoritative Sources & Proof Citations ({len(sources)} cited)",
            ])
            if sources:
                for idx, src in enumerate(sources, 1):
                    inacc = src.get('is_inaccessible', False)
                    doc_title = src.get('document_title', 'Untitled Document')
                    rank = src.get('authority_level', 1)
                    status = src.get('document_status', 'approved')
                    page = src.get('page_number')
                    page_str = f", Page {page}" if page is not None else ""
                    section = src.get('section')
                    sec_str = f", Section: {section}" if section else ""
                    passage = src.get('shortest_passage') or src.get('passage') or ''

                    if inacc:
                        lines.append(f"{idx}. **{doc_title}** *(Access Restricted or Archived)*{page_str}{sec_str}")
                        lines.append(f"   - Notice: Source document access restricted; passage redacted for privacy.")
                    else:
                        lines.append(f"{idx}. **{doc_title}** (Authority Rank {rank} • Status: {status}){page_str}{sec_str}")
                        lines.append(f"   - **Evidence Type:** `{src.get('evidence_type', 'direct')}`")
                        lines.append(f"   - **Quoted Source Proof:**")
                        lines.append(f"     > \"{passage}\"")
            else:
                lines.append("*No external source passages disclosed for this turn.*")

            lines.extend(["", "---", ""])

        return "\n".join(lines)

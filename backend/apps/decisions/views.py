from typing import Any
from django.db.models import Q
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.workspaces.models import Workspace
from apps.audit.models import AuditEvent
from .models import DecisionRecord, Conversation, ChatMessage
from .serializers import (
    DecisionRecordSerializer,
    ConversationListSerializer,
    ConversationDetailSerializer,
    ChatMessageSerializer
)
from .services import ConversationService


class DecisionRecordViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DecisionRecordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        req: Any = self.request
        user = req.user
        ws_id = req.query_params.get('workspace_id') or req.query_params.get('workspace')
        qs = DecisionRecord.objects.filter(workspace__memberships__user=user)
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.distinct()


class ConversationViewSet(viewsets.ModelViewSet):
    """
    CRUD and Turn Execution ViewSet for Persistent Chat History.
    Guarantees user and workspace tenancy, prevents IDOR vulnerabilities,
    and supports multi-turn governed inquiry.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ConversationDetailSerializer
        return ConversationListSerializer

    def get_queryset(self):
        req: Any = self.request
        user = req.user
        ws_id = req.query_params.get('workspace') or req.query_params.get('workspace_id')
        
        # Base filter: Only non-deleted conversations owned by requesting user in workspaces they belong to
        qs = Conversation.objects.filter(
            user=user,
            workspace__memberships__user=user,
            is_deleted=False
        )

        if ws_id:
            qs = qs.filter(workspace_id=ws_id)

        archived = req.query_params.get('archived')
        if archived is not None:
            is_archived = archived.lower() in ('true', '1')
            qs = qs.filter(is_archived=is_archived)

        search = req.query_params.get('search')
        if search and search.strip():
            term = search.strip()
            qs = qs.filter(
                Q(title__icontains=term) | Q(messages__content__icontains=term)
            ).distinct()

        return qs.order_by('-last_activity_at')

    def create(self, request, *args, **kwargs):
        ws_id = request.data.get('workspace') or request.data.get('workspace_id')
        if not ws_id:
            return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        workspace = Workspace.objects.filter(id=ws_id).first()
        if not workspace:
            return Response({'error': 'Workspace not found.'}, status=status.HTTP_404_NOT_FOUND)

        title = request.data.get('title')
        document_id = request.data.get('document') or request.data.get('document_id')
        collection_id = request.data.get('collection') or request.data.get('collection_id')

        try:
            conversation = ConversationService.create_conversation(
                workspace=workspace,
                user=request.user,
                title=title,
                document_id=document_id,
                collection_id=collection_id
            )
            serializer = ConversationDetailSerializer(conversation, context={'request': request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except PermissionDenied as pe:
            return Response({'error': str(pe)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def partial_update(self, request, pk=None, *args, **kwargs):
        """Allows renaming or archiving a conversation."""
        conversation = self.get_object()

        if 'title' in request.data:
            new_title = request.data.get('title', '').strip()
            if not new_title:
                return Response({'error': 'Title cannot be blank.'}, status=status.HTTP_400_BAD_REQUEST)
            if len(new_title) > 255:
                new_title = new_title[:250] + '...'
            conversation.title = new_title

        if 'is_archived' in request.data:
            conversation.is_archived = bool(request.data.get('is_archived'))

        conversation.save()
        serializer = ConversationDetailSerializer(conversation, context={'request': request})
        return Response(serializer.data)

    def destroy(self, request, pk=None, *args, **kwargs):
        """Soft deletes conversation following enterprise audit retention policy."""
        conversation = self.get_object()
        conversation.is_deleted = True
        conversation.save(update_fields=['is_deleted', 'updated_at'])

        AuditEvent.objects.create(
            organization=conversation.organization,
            workspace=conversation.workspace,
            user=request.user,
            event_type='decision_recorded',
            target_type='conversation',
            target_id=str(conversation.id),
            details={'action': 'conversation_deleted', 'title': conversation.title}
        )

        return Response({'status': 'deleted', 'id': str(conversation.id)}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get', 'post'], url_path='messages')
    def messages(self, request, pk=None):
        """
        GET: Retrieves messages for this conversation.
        POST: Submits a new question turn, evaluates via Governed RAG, and persists response.
        """
        conversation = self.get_object()

        if request.method == 'GET':
            msgs = conversation.messages.order_by('sequence_number', 'created_at')
            serializer = ChatMessageSerializer(msgs, many=True, context={'request': request})
            return Response(serializer.data)

        # POST: Submit Turn
        query = request.data.get('query') or request.data.get('content')
        if not query or not query.strip():
            return Response({'error': 'query parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)

        client_message_id = request.data.get('client_message_id')
        document_id = request.data.get('document_id') or request.data.get('document')
        collection_id = request.data.get('collection_id') or request.data.get('collection')
        groq_api_key = (
            request.data.get('groq_api_key') or
            request.headers.get('X-Groq-Api-Key')
        )
        llm_model = (
            request.data.get('llm_model') or
            request.headers.get('X-LLM-Model') or
            'gpt-oss-120B'
        )
        execution_mode = request.data.get('execution_mode') or request.headers.get('X-Execution-Mode')
        synthesis_mode = request.data.get('synthesis_mode') or request.headers.get('X-Synthesis-Mode')
        as_of = request.data.get('as_of')

        try:
            user_msg, assistant_msg, envelope = ConversationService.submit_turn(
                conversation=conversation,
                user=request.user,
                query=query,
                client_message_id=client_message_id,
                document_id=document_id,
                collection_id=collection_id,
                groq_api_key=groq_api_key,
                llm_model=llm_model,
                execution_mode=execution_mode,
                synthesis_mode=synthesis_mode,
                as_of=as_of
            )

            return Response({
                'conversation_id': str(conversation.id),
                'conversation_title': conversation.title,
                'user_message': ChatMessageSerializer(user_msg, context={'request': request}).data,
                'assistant_message': ChatMessageSerializer(assistant_msg, context={'request': request}).data,
                'result': envelope,
            }, status=status.HTTP_200_OK if assistant_msg.status == 'completed' else status.HTTP_202_ACCEPTED)

        except PermissionDenied as pe:
            return Response({'error': str(pe)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as ve:
            return Response({'error': str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as ex:
            return Response({'error': f"Internal turn error: {ex}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

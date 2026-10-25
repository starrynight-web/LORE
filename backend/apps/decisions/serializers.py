from rest_framework import serializers
from .models import DecisionRecord, Conversation, ChatMessage
from .services import ConversationService


class DecisionRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DecisionRecord
        fields = [
            'id', 'trace_id', 'workspace', 'user', 'query',
            'decision_type', 'state', 'directive', 'answer_text',
            'evidence_found', 'evidence_missing', 'conflicts_resolved',
            'citations', 'token_count', 'created_at'
        ]


class ChatMessageSerializer(serializers.ModelSerializer):
    revalidated_citations = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            'id', 'conversation', 'role', 'content', 'sequence_number',
            'status', 'decision', 'governance_state', 'governance_directive',
            'trace_id', 'citations', 'revalidated_citations', 'evidence_missing',
            'conflicts_resolved', 'layers_breakdown', 'retrieval_config',
            'client_message_id', 'error_message', 'created_at'
        ]

    def get_revalidated_citations(self, obj: ChatMessage):
        """
        Revalidates access permissions for all cited documents at query time.
        Redacts content if a document was deleted or access revoked (Requirement 6 & 7).
        """
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        if not user or not obj.citations:
            return obj.citations or []

        try:
            return ConversationService.revalidate_citations(
                citations=obj.citations,
                user=user,
                workspace=obj.conversation.workspace
            )
        except Exception:
            return obj.citations or []


class ConversationListSerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)
    document_title = serializers.CharField(source='document.title', read_only=True, allow_null=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    message_count = serializers.SerializerMethodField()
    last_message_preview = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'title', 'workspace', 'workspace_name', 'user', 'user_username',
            'document', 'document_title', 'collection', 'is_archived',
            'message_count', 'last_message_preview', 'created_at', 'updated_at',
            'last_activity_at'
        ]

    def get_message_count(self, obj: Conversation) -> int:
        return obj.messages.count()

    def get_last_message_preview(self, obj: Conversation) -> str:
        last = obj.messages.order_by('-sequence_number').first()
        if not last:
            return ""
        return (last.content[:100] + '...') if len(last.content) > 100 else last.content


class ConversationDetailSerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)
    document_title = serializers.CharField(source='document.title', read_only=True, allow_null=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    messages = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'title', 'workspace', 'workspace_name', 'user', 'user_username',
            'document', 'document_title', 'collection', 'is_archived',
            'messages', 'created_at', 'updated_at', 'last_activity_at'
        ]

    def get_messages(self, obj: Conversation):
        # Order chronologically for seamless chat display
        msgs = obj.messages.order_by('sequence_number', 'created_at')
        return ChatMessageSerializer(msgs, many=True, context=self.context).data

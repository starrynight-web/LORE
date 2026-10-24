from typing import Any
from rest_framework import serializers, viewsets, permissions
from .models import DecisionRecord

class DecisionRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DecisionRecord
        fields = [
            'id', 'trace_id', 'workspace', 'user', 'query',
            'decision_type', 'state', 'directive', 'answer_text',
            'evidence_found', 'evidence_missing', 'conflicts_resolved',
            'citations', 'token_count', 'created_at'
        ]

class DecisionRecordViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DecisionRecordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        req: Any = self.request
        user = req.user
        ws_id = req.query_params.get('workspace_id')
        qs = DecisionRecord.objects.filter(workspace__memberships__user=user)
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.distinct()

from rest_framework import serializers, viewsets, permissions
from .models import AuditEvent

class AuditEventSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = AuditEvent
        fields = [
            'id', 'organization', 'workspace', 'user', 'username',
            'event_type', 'target_type', 'target_id', 'details',
            'ip_address', 'created_at'
        ]

class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditEventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        ws_id = self.request.query_params.get('workspace_id')
        qs = AuditEvent.objects.filter(workspace__memberships__user=user)
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.distinct()

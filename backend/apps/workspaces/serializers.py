from rest_framework import serializers
from .models import Workspace, WorkspaceMembership, Collection
from apps.identity.serializers import UserSerializer

class WorkspaceSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField(read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Workspace
        fields = ['id', 'organization', 'organization_name', 'name', 'slug', 'description', 'is_default', 'role', 'created_at', 'updated_at']

    def get_role(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            membership = WorkspaceMembership.objects.filter(workspace=obj, user=request.user).first()
            return membership.role if membership else None
        return None

class CollectionSerializer(serializers.ModelSerializer):
    document_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Collection
        fields = ['id', 'workspace', 'name', 'description', 'color', 'icon', 'document_count', 'created_at', 'updated_at']

    def get_document_count(self, obj):
        return getattr(obj, 'documents', None).count() if hasattr(obj, 'documents') else 0

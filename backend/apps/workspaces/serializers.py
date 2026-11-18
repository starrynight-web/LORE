from rest_framework import serializers
from django.utils.text import slugify
from .models import Workspace, WorkspaceMembership, Collection
from apps.identity.serializers import UserSerializer

class WorkspaceSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField(read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    slug = serializers.SlugField(required=False, default='')

    class Meta:
        model = Workspace
        fields = ['id', 'organization', 'organization_name', 'name', 'slug', 'description', 'is_default', 'role', 'created_at', 'updated_at']
        validators = []

    def validate(self, attrs):
        org = attrs.get('organization') or (self.instance.organization if self.instance else None)
        name = attrs.get('name') or (self.instance.name if self.instance else '')
        slug = attrs.get('slug')
        base_slug = slugify(slug or name) or 'workspace'
        slug = base_slug
        counter = 1
        qs = Workspace.objects.filter(organization=org, slug=slug)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        while qs.exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
            qs = Workspace.objects.filter(organization=org, slug=slug)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
        attrs['slug'] = slug
        return attrs

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
        docs = getattr(obj, 'documents', None)
        return docs.count() if docs is not None else 0

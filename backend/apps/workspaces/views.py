from typing import Any
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from django.utils.text import slugify
from django.shortcuts import get_object_or_404
from .models import Workspace, WorkspaceMembership, Collection
from .serializers import WorkspaceSerializer, CollectionSerializer
from apps.identity.models import Organization, OrganizationMembership

class WorkspaceViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspaceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        req: Any = self.request
        user = req.user
        org_id = req.query_params.get('organization_id')
        qs = Workspace.objects.filter(memberships__user=user)
        if org_id:
            qs = qs.filter(organization_id=org_id)
        return qs.distinct()

    def perform_create(self, serializer):
        org = serializer.validated_data.get('organization')
        # Check org admin/owner permission
        org_mem = get_object_or_404(OrganizationMembership, organization=org, user=self.request.user)
        name = serializer.validated_data.get('name')
        base_slug = slugify(name) or 'workspace'
        slug = base_slug
        counter = 1
        while Workspace.objects.filter(organization=org, slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        ws = serializer.save(slug=slug)
        WorkspaceMembership.objects.create(workspace=ws, user=self.request.user, role='workspace_admin')

class CollectionViewSet(viewsets.ModelViewSet):
    serializer_class = CollectionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        req: Any = self.request
        user = req.user
        ws_id = req.query_params.get('workspace_id')
        qs = Collection.objects.filter(workspace__memberships__user=user)
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.distinct()

    def perform_create(self, serializer):
        ws = serializer.validated_data.get('workspace')
        get_object_or_404(WorkspaceMembership, workspace=ws, user=self.request.user)
        serializer.save()

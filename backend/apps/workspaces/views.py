from typing import Any
import os
import logging
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.text import slugify
from django.shortcuts import get_object_or_404
from .models import Workspace, WorkspaceMembership, Collection
from .serializers import WorkspaceSerializer, CollectionSerializer
from apps.identity.models import Organization, OrganizationMembership

logger = logging.getLogger(__name__)

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
        ws = serializer.save()
        WorkspaceMembership.objects.create(workspace=ws, user=self.request.user, role='workspace_admin')

    @action(detail=True, methods=['post'], url_path='purge-data')
    def purge_data(self, request, pk=None):
        """
        Deletes all documents, knowledge entities, relationships, RAPTOR domain summaries,
        chunks, and vector embeddings (Qdrant & pgvector) for this specific workspace,
        resetting it to a pristine state without deleting the workspace itself.
        """
        workspace = self.get_object()
        user = request.user
        
        # Verify user is workspace_admin or org admin/owner
        mem = WorkspaceMembership.objects.filter(workspace=workspace, user=user).first()
        org_mem = OrganizationMembership.objects.filter(organization=workspace.organization, user=user).first()
        is_admin = (mem and mem.role == 'workspace_admin') or (org_mem and org_mem.role in ['owner', 'admin'])
        if not is_admin:
            return Response(
                {'error': 'Permission denied. Only workspace or organization administrators can purge database records.'},
                status=status.HTTP_403_FORBIDDEN
            )

        ws_id_str = str(workspace.id)

        # 1. Clean up vector storage (Qdrant & pgvector)
        try:
            from apps.retrieval.vector_store import QdrantVectorStore, PgVectorStorage
            qstore = QdrantVectorStore()
            if hasattr(qstore, 'delete_workspace_vectors'):
                qstore.delete_workspace_vectors("lore_chunks", ws_id_str)
            pstore = PgVectorStorage()
            if hasattr(pstore, 'delete_workspace_vectors'):
                pstore.delete_workspace_vectors("lore_chunks", ws_id_str)
        except Exception as e:
            logger.warning(f"Error purging vectors for workspace {ws_id_str}: {e}")

        # 2. Delete source document physical files & database records
        from apps.sources.models import SourceDocument
        docs = SourceDocument.objects.filter(workspace=workspace)
        docs_count = docs.count()
        for doc in docs:
            try:
                if doc.file_obj and os.path.exists(doc.file_obj.path):
                    os.remove(doc.file_obj.path)
            except Exception:
                pass
        docs.delete()

        # 3. Delete knowledge entities, edges, RAPTOR summaries, items, chunks
        from apps.knowledge.models import CanonicalEntity, KnowledgeRelationship, DomainSummary, KnowledgeItem, DocumentChunk
        entities_count = CanonicalEntity.objects.filter(workspace=workspace).count()
        CanonicalEntity.objects.filter(workspace=workspace).delete()
        KnowledgeRelationship.objects.filter(workspace=workspace).delete()
        DomainSummary.objects.filter(workspace=workspace).delete()
        KnowledgeItem.objects.filter(workspace=workspace).delete()
        DocumentChunk.objects.filter(workspace=workspace).delete()

        # 4. Clean up governance records (exceptions, requirements, conflicts)
        from apps.governance.models import ScopedException, EvidenceRequirement, ConflictRecord
        ScopedException.objects.filter(workspace=workspace).delete()
        EvidenceRequirement.objects.filter(workspace=workspace).delete()
        ConflictRecord.objects.filter(workspace=workspace).delete()

        # 5. Clean up ingestion jobs
        from apps.ingestion.models import IngestionJob
        IngestionJob.objects.filter(workspace=workspace).delete()

        return Response({
            'status': 'SUCCESS',
            'message': f'Workspace database purged successfully. Deleted {docs_count} documents, {entities_count} knowledge entities, and all corresponding vector embeddings.',
            'workspace_id': ws_id_str,
            'deleted_documents_count': docs_count,
            'deleted_entities_count': entities_count,
        })

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

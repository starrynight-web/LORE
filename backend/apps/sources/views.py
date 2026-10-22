import os
import time
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.conf import settings

from .models import SourceDocument, DocumentVersion, DocumentPage
from .serializers import SourceDocumentSerializer, DocumentPageSerializer, DocumentVersionSerializer
from .services import StorageSecurityService
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.ingestion.models import IngestionJob
from apps.ingestion.tasks import process_ingestion_pipeline, process_document_job
from apps.ingestion.pipeline.extractors import UnifiedDocumentExtractor
from apps.ingestion.pipeline.ocr import repair_visual_bengali_document, bangla_to_arabic_digits
from apps.audit.models import AuditEvent

class SourceDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = SourceDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        ws_id = self.request.query_params.get('workspace_id')
        collection_id = self.request.query_params.get('collection_id')
        status_filter = self.request.query_params.get('status')
        doc_type = self.request.query_params.get('document_type')

        qs = SourceDocument.objects.filter(workspace__memberships__user=user)
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        if collection_id:
            qs = qs.filter(collection_id=collection_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if doc_type:
            qs = qs.filter(document_type=doc_type)

        return qs.distinct()

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        workspace_id = request.data.get('workspace')
        collection_id = request.data.get('collection')
        title = request.data.get('title')
        description = request.data.get('description', '')
        authority_level = int(request.data.get('authority_level', 3))

        if not file_obj:
            return Response({'error': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)
        if not workspace_id:
            return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        workspace = get_object_or_404(Workspace, id=workspace_id, memberships__user=request.user)

        # 1. Validate file size and magic bytes
        try:
            sec_meta = StorageSecurityService.inspect_and_validate(file_obj)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Check collection if provided
        collection = None
        if collection_id:
            collection = workspace.collections.filter(id=collection_id).first()

        # 3. Create SourceDocument
        doc = SourceDocument.objects.create(
            organization=workspace.organization,
            workspace=workspace,
            collection=collection,
            owner=request.user,
            title=title or file_obj.name,
            description=description,
            original_filename=file_obj.name,
            mime_type=sec_meta['mime_type'],
            file_size=sec_meta['file_size'],
            file_hash=sec_meta['file_hash'],
            file_obj=file_obj,
            document_type=sec_meta['document_type'],
            authority_level=authority_level,
            status='queued'
        )

        # 4. Create initial DocumentVersion
        DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            file_hash=sec_meta['file_hash'],
            file_obj=doc.file_obj,
            change_summary='Initial upload',
            is_current=True
        )

        # 5. Create IngestionJob
        job = IngestionJob.objects.create(
            document=doc,
            organization=workspace.organization,
            workspace=workspace,
            status='queued',
            current_stage='inspection'
        )

        # 6. Log Audit Event
        AuditEvent.objects.create(
            organization=workspace.organization,
            workspace=workspace,
            user=request.user,
            event_type='document_uploaded',
            target_type='document',
            target_id=str(doc.id),
            details={'filename': file_obj.name, 'size': sec_meta['file_size'], 'sha256': sec_meta['file_hash']}
        )

        # 7. Dispatch background ingestion task
        if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True):
            # Run synchronously for instant dev/test feedback
            process_ingestion_pipeline(str(job.id))
            doc.refresh_from_db()
            job.refresh_from_db()
        else:
            process_document_job.delay(str(job.id))

        return Response({
            'document': SourceDocumentSerializer(doc).data,
            'job_id': str(job.id),
            'status': doc.status
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def pages(self, request, pk=None):
        doc = self.get_object()
        pages = doc.pages.all()
        return Response(DocumentPageSerializer(pages, many=True).data)

    @action(detail=True, methods=['post'])
    def reprocess(self, request, pk=None):
        doc = self.get_object()
        job = IngestionJob.objects.create(
            document=doc,
            organization=doc.organization,
            workspace=doc.workspace,
            status='queued',
            current_stage='inspection'
        )
        if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True):
            process_ingestion_pipeline(str(job.id))
            doc.refresh_from_db()
            job.refresh_from_db()
        else:
            process_document_job.delay(str(job.id))

        return Response({'message': 'Reprocessing triggered', 'job_id': str(job.id)})

    @action(detail=False, methods=['post'], url_path='live-ocr', permission_classes=[permissions.AllowAny])
    def live_ocr(self, request):
        """
        Real-time Optical Character Recognition & Document Extraction endpoint.
        Processes uploaded PDF or image immediately and returns token bounding boxes,
        confidences, character metrics, and Unicode repaired text in real-time.
        """
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided for real-time OCR.'}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Inspect magic bytes & compute hash
        try:
            sec_meta = StorageSecurityService.inspect_and_validate(file_obj)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        bengali_repair = request.data.get('bengali_repair', 'true').lower() in ('true', '1', 'yes')
        arabic_digits = request.data.get('arabic_digits', 'false').lower() in ('true', '1', 'yes')
        save_to_workspace = request.data.get('save_to_workspace', 'false').lower() in ('true', '1', 'yes')
        workspace_id = request.data.get('workspace')

        file_obj.seek(0)
        file_bytes = file_obj.read()

        t0 = time.time()
        extractor = UnifiedDocumentExtractor()
        pages = extractor.extract_document(
            file_path_or_bytes=file_bytes,
            doc_type=sec_meta['document_type'],
            filename=file_obj.name
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        # Apply script options if specified
        for p in pages:
            if bengali_repair and p.get('text'):
                p['text'] = repair_visual_bengali_document(p['text'])
            if arabic_digits and p.get('text'):
                p['text'] = bangla_to_arabic_digits(p['text'])

        avg_conf = (
            sum(p.get('confidence', 1.0) for p in pages) / max(len(pages), 1)
        )

        saved_doc_id = None
        if save_to_workspace and workspace_id:
            if not request.user or not request.user.is_authenticated:
                return Response({'error': 'Authentication required to save document to workspace.'}, status=status.HTTP_401_UNAUTHORIZED)
            workspace = get_object_or_404(Workspace, id=workspace_id, memberships__user=request.user)
            file_obj.seek(0)
            doc = SourceDocument.objects.create(
                organization=workspace.organization,
                workspace=workspace,
                owner=request.user,
                title=request.data.get('title', file_obj.name),
                description=request.data.get('description', 'Live OCR Document'),
                original_filename=file_obj.name,
                mime_type=sec_meta['mime_type'],
                file_size=sec_meta['file_size'],
                file_hash=sec_meta['file_hash'],
                file_obj=file_obj,
                document_type=sec_meta['document_type'],
                authority_level=int(request.data.get('authority_level', 3)),
                status='uploaded',
                ocr_confidence=round(avg_conf, 3),
                page_count=len(pages)
            )

            # Create Version record
            DocumentVersion.objects.create(
                document=doc,
                version_number=1,
                file_size=sec_meta['file_size'],
                file_hash=sec_meta['file_hash'],
                file_obj=doc.file_obj,
                change_summary='Real-time Live OCR Ingestion',
                is_current=True
            )

            # Create IngestionJob and execute chunking, embedding, vector indexing
            job = IngestionJob.objects.create(
                document=doc,
                organization=workspace.organization,
                workspace=workspace,
                status='queued',
                current_stage='inspection'
            )
            process_ingestion_pipeline(str(job.id))
            doc.refresh_from_db()
            saved_doc_id = str(doc.id)

            AuditEvent.objects.create(
                organization=workspace.organization,
                workspace=workspace,
                user=request.user,
                event_type='document_uploaded',
                target_type='document',
                target_id=str(doc.id),
                details={'filename': file_obj.name, 'source': 'realtime_live_ocr', 'sha256': sec_meta['file_hash']}
            )

        return Response({
            'status': 'success',
            'filename': file_obj.name,
            'file_hash': sec_meta['file_hash'],
            'document_type': sec_meta['document_type'],
            'pages': pages,
            'page_count': len(pages),
            'ocr_confidence': round(avg_conf, 3),
            'total_words': sum(p.get('words_count', 0) for p in pages),
            'timings_ms': elapsed_ms,
            'document_id': saved_doc_id
        })


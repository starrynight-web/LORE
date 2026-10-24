import os
import time
from typing import Any
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.conf import settings

from .models import SourceDocument, DocumentVersion, DocumentPage
from .serializers import SourceDocumentSerializer, DocumentPageSerializer, DocumentVersionSerializer
from .services import StorageSecurityService
from apps.workspaces.models import Workspace, WorkspaceMembership, Collection
from apps.ingestion.models import IngestionJob
from apps.ingestion.tasks import process_ingestion_pipeline, process_document_job
from apps.ingestion.pipeline.extractors import UnifiedDocumentExtractor
from apps.ingestion.pipeline.ocr import repair_visual_bengali_document, bangla_to_arabic_digits
from apps.audit.models import AuditEvent

class SourceDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = SourceDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self) -> Any:
        req: Any = self.request
        user = req.user
        ws_id = req.query_params.get('workspace_id')
        collection_id = req.query_params.get('collection_id')
        status_filter = req.query_params.get('status')
        doc_type = req.query_params.get('document_type')

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

    def _ingest_single_file(self, file_obj, workspace, collection, user, title=None, description='', authority_level=3):
        """Validates, stores, registers, and triggers pipeline ingestion for a single document."""
        # 1. Validate file size, magic bytes, and format support
        sec_meta = StorageSecurityService.inspect_and_validate(file_obj)

        # 2. Check SaaS Storage & Document Quotas
        from apps.subscriptions.services import QuotaEnforcementService
        QuotaEnforcementService.check_upload_quota(workspace.organization, sec_meta['file_size'])

        # 3. Create SourceDocument anchored strictly to this file's identity
        doc = SourceDocument.objects.create(
            organization=workspace.organization,
            workspace=workspace,
            collection=collection,
            owner=user,
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

        # Record usage
        QuotaEnforcementService.record_upload(workspace.organization, workspace, sec_meta['file_size'])

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
            user=user,
            event_type='document_uploaded',
            target_type='document',
            target_id=str(doc.id),
            details={'filename': file_obj.name, 'size': sec_meta['file_size'], 'sha256': sec_meta['file_hash']}
        )

        # 7. Dispatch background ingestion task
        if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True):
            process_ingestion_pipeline(str(job.id))
            doc.refresh_from_db()
            job.refresh_from_db()
        else:
            task: Any = process_document_job
            task.delay(str(job.id))

        return doc, job

    def create(self, request, *args, **kwargs):
        uploaded_files = []
        if 'files' in request.FILES:
            uploaded_files = request.FILES.getlist('files')
        elif 'file' in request.FILES:
            uploaded_files = request.FILES.getlist('file')

        if not uploaded_files:
            return Response({'error': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)

        workspace_id = request.data.get('workspace')
        if not workspace_id:
            return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        workspace = get_object_or_404(Workspace, id=workspace_id, memberships__user=request.user)

        collection_id = request.data.get('collection')
        collection = None
        if collection_id:
            collection = Collection.objects.filter(workspace=workspace, id=collection_id).first()

        authority_level = int(request.data.get('authority_level', 3))
        description = request.data.get('description', '')

        # Single file upload path (backward compatible contract)
        if len(uploaded_files) == 1:
            file_obj = uploaded_files[0]
            title = request.data.get('title')
            try:
                doc, job = self._ingest_single_file(
                    file_obj=file_obj,
                    workspace=workspace,
                    collection=collection,
                    user=request.user,
                    title=title,
                    description=description,
                    authority_level=authority_level
                )
                return Response({
                    'document': SourceDocumentSerializer(doc).data,
                    'job_id': str(job.id),
                    'status': doc.status
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                is_quota = 'quota' in str(e).lower()
                status_code = status.HTTP_402_PAYMENT_REQUIRED if is_quota else status.HTTP_400_BAD_REQUEST
                resp_payload: dict[str, Any] = {'error': str(e)}
                if is_quota:
                    resp_payload['quota_exceeded'] = True
                return Response(resp_payload, status=status_code)

        # Multi-file upload path
        created_docs = []
        created_jobs = []
        errors = []

        import json
        titles_map = {}
        raw_titles = request.data.get('titles')
        if raw_titles:
            try:
                titles_map = json.loads(raw_titles) if isinstance(raw_titles, str) else raw_titles
            except Exception:
                titles_map = {}

        base_title = request.data.get('title')

        for idx, file_obj in enumerate(uploaded_files):
            file_title = None
            if isinstance(titles_map, dict) and file_obj.name in titles_map:
                file_title = titles_map[file_obj.name]
            elif isinstance(titles_map, list) and idx < len(titles_map):
                file_title = titles_map[idx]
            elif base_title and len(uploaded_files) == 1:
                file_title = base_title
            elif base_title:
                file_title = f"{base_title} - {file_obj.name}"
            else:
                file_title = os.path.splitext(file_obj.name)[0]

            try:
                doc, job = self._ingest_single_file(
                    file_obj=file_obj,
                    workspace=workspace,
                    collection=collection,
                    user=request.user,
                    title=file_title,
                    description=description,
                    authority_level=authority_level
                )
                created_docs.append(doc)
                created_jobs.append(job)
            except Exception as e:
                errors.append({'filename': file_obj.name, 'error': str(e)})

        if not created_docs and errors:
            first_err = errors[0]['error']
            is_quota = 'quota' in first_err.lower()
            status_code = status.HTTP_402_PAYMENT_REQUIRED if is_quota else status.HTTP_400_BAD_REQUEST
            return Response({'error': 'All document uploads failed.', 'details': errors}, status=status_code)

        return Response({
            'documents': SourceDocumentSerializer(created_docs, many=True).data,
            'job_ids': [str(j.id) for j in created_jobs],
            'jobs': [{'document_id': str(d.id), 'job_id': str(j.id), 'status': d.status} for d, j in zip(created_docs, created_jobs)],
            'count': len(created_docs),
            'document': SourceDocumentSerializer(created_docs[0]).data if created_docs else None,
            'job_id': str(created_jobs[0].id) if created_jobs else None,
            'status': created_docs[0].status if created_docs else None,
            'errors': errors
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='bulk-upload')
    def bulk_upload(self, request):
        """
        Batch upload multiple documents of diverse supported formats.
        Isolates each document's metadata and extraction to prevent cross-document hallucination.
        Supports partial success: valid files are ingested even if one malformed file fails.
        """
        uploaded_files = []
        if 'files' in request.FILES:
            uploaded_files = request.FILES.getlist('files')
        elif 'file' in request.FILES:
            uploaded_files = request.FILES.getlist('file')

        if not uploaded_files:
            return Response({'error': 'No files provided for bulk upload.'}, status=status.HTTP_400_BAD_REQUEST)

        workspace_id = request.data.get('workspace')
        if not workspace_id:
            return Response({'error': 'workspace ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        workspace = get_object_or_404(Workspace, id=workspace_id, memberships__user=request.user)

        collection_id = request.data.get('collection')
        collection = None
        if collection_id:
            collection = Collection.objects.filter(workspace=workspace, id=collection_id).first()

        authority_level = int(request.data.get('authority_level', 3))
        description = request.data.get('description', '')

        import json
        titles_map = {}
        raw_titles = request.data.get('titles')
        if raw_titles:
            try:
                titles_map = json.loads(raw_titles) if isinstance(raw_titles, str) else raw_titles
            except Exception:
                titles_map = {}

        base_title = request.data.get('title')

        successful_docs = []
        failed_files = []

        for idx, file_obj in enumerate(uploaded_files):
            file_title = None
            if isinstance(titles_map, dict) and file_obj.name in titles_map:
                file_title = titles_map[file_obj.name]
            elif isinstance(titles_map, list) and idx < len(titles_map):
                file_title = titles_map[idx]
            elif base_title and len(uploaded_files) == 1:
                file_title = base_title
            elif base_title:
                file_title = f"{base_title} - {file_obj.name}"
            else:
                file_title = os.path.splitext(file_obj.name)[0]

            try:
                doc, job = self._ingest_single_file(
                    file_obj=file_obj,
                    workspace=workspace,
                    collection=collection,
                    user=request.user,
                    title=file_title,
                    description=description,
                    authority_level=authority_level
                )
                successful_docs.append({
                    'document': SourceDocumentSerializer(doc).data,
                    'job_id': str(job.id),
                    'status': doc.status
                })
            except Exception as e:
                failed_files.append({
                    'filename': file_obj.name,
                    'error': str(e)
                })

        overall_status = 'success' if not failed_files else ('partial_success' if successful_docs else 'failed')
        http_status = status.HTTP_201_CREATED if successful_docs else status.HTTP_400_BAD_REQUEST

        return Response({
            'status': overall_status,
            'total_count': len(uploaded_files),
            'success_count': len(successful_docs),
            'failed_count': len(failed_files),
            'successful': successful_docs,
            'failed': failed_files,
            'documents': [item['document'] for item in successful_docs],
            'job_ids': [item['job_id'] for item in successful_docs],
            'document': successful_docs[0]['document'] if successful_docs else None,
            'job_id': successful_docs[0]['job_id'] if successful_docs else None,
            'doc_status': successful_docs[0]['status'] if successful_docs else None
        }, status=http_status)

    def perform_destroy(self, instance):
        """Cascading cleanup of vectors, storage files, and relational data."""
        try:
            from apps.retrieval.vector_store import QdrantVectorStore
            vstore = QdrantVectorStore()
            vstore.delete_document_chunks("lore_chunks", str(instance.id))
        except Exception:
            pass

        try:
            if instance.file_obj and os.path.exists(instance.file_obj.path):
                os.remove(instance.file_obj.path)
        except Exception:
            pass

        instance.delete()

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Backend-mediated secure authorized document download."""
        doc = self.get_object()
        if not doc.file_obj or not os.path.exists(doc.file_obj.path):
            return Response({'error': 'Original document file not found.'}, status=status.HTTP_404_NOT_FOUND)
        
        from django.http import FileResponse
        response = FileResponse(open(doc.file_obj.path, 'rb'), content_type=doc.mime_type)
        response['Content-Disposition'] = f'attachment; filename="{doc.original_filename}"'
        return response

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
            task: Any = process_document_job
            task.delay(str(job.id))

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


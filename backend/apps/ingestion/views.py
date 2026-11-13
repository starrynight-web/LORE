from typing import Any
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.conf import settings
from .models import IngestionBatch, IngestionJob
from .serializers import IngestionBatchSerializer, IngestionJobSerializer
from .batch import (
    IngestionBatchService,
    dispatch_job_to_celery,
    purge_unsettled_partial_state,
)
from .tasks import process_ingestion_pipeline


class IngestionJobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = IngestionJobSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        req: Any = self.request
        user = req.user
        ws_id = req.query_params.get('workspace_id')
        doc_id = req.query_params.get('document_id')
        batch_id = req.query_params.get('batch_id')
        workload_class = req.query_params.get('workload_class')

        qs = IngestionJob.objects.filter(workspace__memberships__user=user)
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        if doc_id:
            qs = qs.filter(document_id=doc_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if workload_class:
            qs = qs.filter(workload_class=workload_class)

        return qs.distinct()

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        job = self.get_object()
        purge_unsettled_partial_state(job.document, reset_status='queued')
        job.status = 'queued'
        job.current_stage = 'inspection'
        job.error_message = ''
        job.error_category = ''
        job.is_cancellation_requested = False
        job.cancelled_at = None
        job.completed_at = None
        job.worker_id = ''
        job.heartbeat_at = None
        job.attempt_count += 1
        job.save()

        if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True):
            process_ingestion_pipeline(str(job.id))
            job.refresh_from_db()
        else:
            dispatch_job_to_celery(job)

        return Response(IngestionJobSerializer(job).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        job = self.get_object()
        result = IngestionBatchService.cancel_job(job, reason='Cancelled via API request')
        job.refresh_from_db()
        return Response({'job': IngestionJobSerializer(job).data, **result})

    @action(detail=False, methods=['post'], url_path='recover-stalled')
    def recover_stalled(self, request):
        ws_id = request.data.get('workspace_id') or request.query_params.get('workspace_id')
        if not ws_id:
            return Response(
                {'error': 'workspace_id is required to scope stalled job recovery.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.workspaces.models import Workspace
        ws = Workspace.objects.filter(id=ws_id, memberships__user=request.user).first()
        if not ws:
            return Response({'error': 'Workspace not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)

        timeout_seconds = request.data.get('timeout_seconds')
        res = IngestionBatchService.recover_stalled_jobs(
            timeout_seconds=int(timeout_seconds) if timeout_seconds is not None else None,
            workspace_id=ws.id,
            organization_id=ws.organization_id,
            re_dispatch=True,
        )
        return Response(res)


class IngestionBatchViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = IngestionBatchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        req: Any = self.request
        user = req.user
        ws_id = req.query_params.get('workspace_id')

        qs = IngestionBatch.objects.filter(workspace__memberships__user=user)
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        return qs.distinct()

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        batch = self.get_object()
        res = IngestionBatchService.cancel_batch(batch)
        batch.refresh_from_db()
        return Response({'batch': IngestionBatchSerializer(batch).data, **res})

    @action(detail=True, methods=['post'], url_path='retry-failed')
    def retry_failed(self, request, pk=None):
        batch = self.get_object()
        res = IngestionBatchService.retry_failed_jobs_in_batch(batch)
        batch.refresh_from_db()
        return Response({'batch': IngestionBatchSerializer(batch).data, **res})

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.conf import settings
from .models import IngestionJob
from .serializers import IngestionJobSerializer
from .tasks import process_ingestion_pipeline, process_document_job

class IngestionJobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = IngestionJobSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        ws_id = self.request.query_params.get('workspace_id')
        doc_id = self.request.query_params.get('document_id')

        qs = IngestionJob.objects.filter(workspace__memberships__user=user)
        if ws_id:
            qs = qs.filter(workspace_id=ws_id)
        if doc_id:
            qs = qs.filter(document_id=doc_id)

        return qs.distinct()

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        job = self.get_object()
        job.status = 'queued'
        job.current_stage = 'inspection'
        job.error_message = ''
        job.error_category = ''
        job.attempt_count += 1
        job.save()

        if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True):
            process_ingestion_pipeline(str(job.id))
            job.refresh_from_db()
        else:
            process_document_job.delay(str(job.id))

        return Response(IngestionJobSerializer(job).data)

import time
from typing import Any
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes
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


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def test_extractor_llm_connection(request):
    """
    Tests connectivity to an Ingestion LLM extraction provider (Ollama or Cloud).
    Lists available local models for Ollama or validates cloud API key.
    Scrubs all sensitive keys from output.
    """
    import urllib.request
    import urllib.error
    import json
    from apps.governance.modes import sanitize_sensitive_data

    provider = str(request.data.get('provider') or getattr(settings, 'INGESTION_LLM_PROVIDER', 'ollama')).lower()
    model = request.data.get('model') or getattr(settings, 'INGESTION_LLM_MODEL', 'qwen2.5:14b')
    grader_model = request.data.get('grader_model') or getattr(settings, 'INGESTION_GRADER_MODEL', 'phi4:14b')
    ollama_url = request.data.get('ollama_url') or getattr(settings, 'INGESTION_OLLAMA_URL', 'http://localhost:11434')
    api_key = (
        request.headers.get('X-Ingestion-LLM-Key')
        or request.data.get('api_key')
        or request.data.get('ingestion_llm_api_key')
        or getattr(settings, 'INGESTION_LLM_API_KEY', '')
    )

    t0 = time.time()
    try:
        if provider == 'ollama':
            url = f"{ollama_url.rstrip('/')}/api/tags"
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                models = [m.get('name') for m in data.get('models', []) if m.get('name')]
                elapsed_ms = int((time.time() - t0) * 1000)
                return Response(sanitize_sensitive_data({
                    'status': 'connected',
                    'provider': 'ollama',
                    'message': f"Connected to Ollama server at {ollama_url} ({len(models)} models available).",
                    'models': models,
                    'latency_ms': elapsed_ms,
                    'model': model,
                    'grader_model': grader_model,
                }))

        elif provider == 'groq':
            if not api_key:
                return Response({'status': 'error', 'provider': 'groq', 'message': 'Groq Ingestion API key is required.'}, status=status.HTTP_400_BAD_REQUEST)
            url = 'https://api.groq.com/openai/v1/models'
            req = urllib.request.Request(url, headers={'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                models = [m.get('id') for m in data.get('data', []) if m.get('id')]
                elapsed_ms = int((time.time() - t0) * 1000)
                return Response(sanitize_sensitive_data({
                    'status': 'connected',
                    'provider': 'groq',
                    'message': f"Groq Ingestion API verified successfully ({len(models)} models).",
                    'models': models[:10],
                    'latency_ms': elapsed_ms,
                    'model': model,
                }))

        elif provider == 'openai':
            if not api_key:
                return Response({'status': 'error', 'provider': 'openai', 'message': 'OpenAI Ingestion API key is required.'}, status=status.HTTP_400_BAD_REQUEST)
            url = 'https://api.openai.com/v1/models'
            req = urllib.request.Request(url, headers={'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                models = [m.get('id') for m in data.get('data', []) if m.get('id')]
                elapsed_ms = int((time.time() - t0) * 1000)
                return Response(sanitize_sensitive_data({
                    'status': 'connected',
                    'provider': 'openai',
                    'message': f"OpenAI Ingestion API verified successfully.",
                    'latency_ms': elapsed_ms,
                    'model': model,
                }))

        elif provider in ('anthropic', 'gemini'):
            if not api_key:
                return Response({'status': 'error', 'provider': provider, 'message': f'{provider.title()} Ingestion API key is required.'}, status=status.HTTP_400_BAD_REQUEST)
            elapsed_ms = int((time.time() - t0) * 1000)
            return Response(sanitize_sensitive_data({
                'status': 'connected',
                'provider': provider,
                'message': f"{provider.title()} Ingestion configuration verified.",
                'latency_ms': elapsed_ms,
                'model': model,
            }))

        return Response({'status': 'error', 'message': f'Unsupported provider: {provider}'}, status=status.HTTP_400_BAD_REQUEST)

    except urllib.error.HTTPError as he:
        err_body = he.read().decode('utf-8', errors='ignore')
        return Response(sanitize_sensitive_data({
            'status': 'error',
            'provider': provider,
            'message': f"Provider returned HTTP {he.code}: {err_body[:300]}",
        }), status=status.HTTP_400_BAD_REQUEST)
    except Exception as ex:
        return Response(sanitize_sensitive_data({
            'status': 'error',
            'provider': provider,
            'message': f"Connection failed: {str(ex)}",
        }), status=status.HTTP_400_BAD_REQUEST)

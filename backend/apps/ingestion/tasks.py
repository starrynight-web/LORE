import logging
import os
from typing import Any, Dict, Optional

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


def process_ingestion_pipeline(
    job_id: str,
    raise_exceptions: bool = False,
    worker_id: Optional[str] = None,
):
    """
    Delegates pipeline execution to the enterprise SequentialPipelineCoordinator
    ensuring sequential Runs 1 to 4 with persistent status, retries, and diagnostics.
    """
    from apps.ingestion.coordinator import SequentialPipelineCoordinator
    return SequentialPipelineCoordinator.orchestrate_pipeline(
        job_id,
        raise_exceptions=raise_exceptions,
        worker_id=worker_id,
    )


class TransientIngestionError(Exception):
    """Errors that are safe and recommended to retry (e.g., network/Qdrant timeouts)."""
    pass


class PermanentIngestionError(Exception):
    """Errors that should not be retried (e.g., corrupt file, unsupported format, security violation)."""
    pass


def _execute_celery_document_job(
    task_self,
    job_id: str,
    forced_workload_class: Optional[str] = None,
) -> Dict[str, Any]:
    from apps.ingestion.batch import (
        WorkloadConcurrencyGate,
        dispatch_pending_batch_jobs,
        purge_unsettled_partial_state,
        sync_batch_status,
    )
    from apps.ingestion.models import IngestionJob
    from apps.ingestion.pipeline.extractors import classify_ingestion_workload

    job = IngestionJob.objects.select_related('document').get(id=job_id)

    if job.is_cancellation_requested or job.status == 'cancelled':
        purge_unsettled_partial_state(job.document, reset_status='failed')
        if job.status != 'cancelled':
            job.status = 'cancelled'
            job.current_stage = 'cancelled'
            job.save(update_fields=['status', 'current_stage', 'updated_at'])
        if job.batch_id:
            sync_batch_status(job.batch_id)
        return {'job_id': str(job.id), 'status': 'cancelled'}

    if job.status == 'ready' and job.document.status == 'ready' and job.pipeline_summary:
        if job.batch_id:
            sync_batch_status(job.batch_id)
        return dict(job.pipeline_summary)

    workload_class = forced_workload_class or job.workload_class or classify_ingestion_workload(
        doc_type=job.document.document_type,
        filename=job.document.original_filename,
        mime_type=getattr(job.document, 'mime_type', ''),
    )
    req_hostname = getattr(getattr(task_self, 'request', None), 'hostname', None)
    worker_id = f"{req_hostname}:{os.getpid()}" if req_hostname else f"celery-{os.getpid()}"

    try:
        with WorkloadConcurrencyGate.acquire(workload_class):
            result = process_ingestion_pipeline(
                job_id,
                raise_exceptions=True,
                worker_id=worker_id,
            )
        return result
    except Exception as exc:
        # Classify transient vs permanent exceptions
        transient_types = (ConnectionError, TimeoutError, OSError, TransientIngestionError)
        is_transient = isinstance(exc, transient_types) or any(
            err_term in str(exc).lower() for err_term in ('connection', 'timeout', 'temporary', 'retry')
        )
        # Permanent errors override transient keyword heuristics
        if isinstance(exc, (ValueError, KeyError, TypeError, FileNotFoundError, PermanentIngestionError)):
            is_transient = False

        current_retries = int(getattr(getattr(task_self, 'request', None), 'retries', 0) or 0)
        max_retries = int(getattr(task_self, 'max_retries', 3) or 3)

        if is_transient and current_retries < max_retries:
            backoff_seconds = (2 ** current_retries) * 5
            logger.warning(
                f"Transient ingestion error for job {job_id} ({workload_class}): {exc}. "
                f"Retrying attempt {current_retries + 2}/{max_retries + 1} in {backoff_seconds}s"
            )
            try:
                job_obj = IngestionJob.objects.select_related('document').get(id=job_id)
                purge_unsettled_partial_state(job_obj.document, reset_status='queued')
                job_obj.status = 'queued'
                job_obj.current_stage = 'inspection'
                job_obj.attempt_count = current_retries + 2
                job_obj.error_message = str(exc)
                job_obj.error_category = 'TRANSIENT_RETRY'
                job_obj.save(
                    update_fields=[
                        'status',
                        'current_stage',
                        'attempt_count',
                        'error_message',
                        'error_category',
                        'updated_at',
                    ]
                )
            except IngestionJob.DoesNotExist:
                pass
            raise task_self.retry(exc=exc, countdown=backoff_seconds)
        else:
            logger.error(f"Permanent ingestion failure or max retries exceeded for job {job_id}: {exc}")
            try:
                job_obj = IngestionJob.objects.select_related('document').get(id=job_id)
                purge_unsettled_partial_state(job_obj.document, reset_status='failed')
                if job_obj.batch_id:
                    sync_batch_status(job_obj.batch_id)
            except IngestionJob.DoesNotExist:
                pass
            raise exc
    finally:
        try:
            refreshed = IngestionJob.objects.filter(id=job_id).values('batch_id').first()
            bid = refreshed.get('batch_id') if refreshed else None
            if bid:
                sync_batch_status(bid)
                if not getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True):
                    dispatch_pending_batch_jobs(bid)
        except Exception as fin_exc:
            logger.warning(f"Batch post-task bookkeeping failed for job {job_id}: {fin_exc}")


@shared_task(bind=True, max_retries=3, acks_late=True, reject_on_worker_lost=True)
def process_document_job(self, job_id: str):
    """
    Backward-compatible Celery task for executing an IngestionJob asynchronously.
    Executes inside the appropriate workload concurrency gate.
    """
    return _execute_celery_document_job(self, job_id)


@shared_task(
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
    queue='ingestion_visual',
)
def process_visual_document_job(self, job_id: str):
    """
    Dedicated heavy Celery task for PDF and image documents routed through
    LORE's visual/OCR subsystem under visual concurrency limits.
    """
    return _execute_celery_document_job(self, job_id, forced_workload_class='visual')


@shared_task(
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
    queue='ingestion_light',
)
def process_lightweight_document_job(self, job_id: str):
    """
    Dedicated lightweight Celery task for ordinary Office (DOCX, XLSX, PPTX, CSV)
    and plaintext documents parsed by existing native extractors.
    """
    return _execute_celery_document_job(self, job_id, forced_workload_class='lightweight')


@shared_task(bind=True, queue='ingestion_light')
def dispatch_ingestion_batch_task(self, batch_id: str):
    """Triggers rolling Celery dispatch for queued items in an IngestionBatch."""
    from apps.ingestion.batch import dispatch_pending_batch_jobs
    return dispatch_pending_batch_jobs(batch_id)


@shared_task(bind=True, queue='ingestion_light')
def recover_stalled_ingestion_jobs_task(
    self,
    timeout_seconds: Optional[int] = None,
    batch_id: Optional[str] = None,
):
    """Recovers jobs stalled by worker crashes/restarts without publishing partial data."""
    from apps.ingestion.batch import IngestionBatchService
    return IngestionBatchService.recover_stalled_jobs(
        timeout_seconds=timeout_seconds,
        batch_id=batch_id,
        re_dispatch=True,
    )

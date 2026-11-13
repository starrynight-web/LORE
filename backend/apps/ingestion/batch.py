import hashlib
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.ingestion.models import IngestionBatch, IngestionJob, IngestionPipelineRun
from apps.ingestion.pipeline.extractors import (
    WorkerExtractorRegistry,
    classify_ingestion_workload,
    needs_visual_extraction,
)
from apps.knowledge.models import DocumentChunk
from apps.retrieval.vector_store import QdrantVectorStore
from apps.sources.models import DocumentPage, DocumentVersion, SourceDocument
from apps.sources.services import StorageSecurityService

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = ('extracting', 'normalizing', 'chunking', 'embedding', 'indexing')
TERMINAL_JOB_STATUSES = ('ready', 'failed', 'needs_review', 'quarantined', 'cancelled')


def get_max_batch_files() -> int:
    return max(1, int(getattr(settings, 'INGESTION_MAX_BATCH_FILES', 100)))


def get_workload_concurrency_limit(workload_class: str) -> int:
    if workload_class.lower() == 'visual':
        return max(1, int(getattr(settings, 'INGESTION_VISUAL_MAX_CONCURRENCY', 1)))
    return max(1, int(getattr(settings, 'INGESTION_LIGHTWEIGHT_MAX_CONCURRENCY', 8)))


def get_workload_queue_name(workload_class: str) -> str:
    if workload_class.lower() == 'visual':
        return str(getattr(settings, 'INGESTION_VISUAL_QUEUE', 'ingestion_visual'))
    return str(getattr(settings, 'INGESTION_LIGHTWEIGHT_QUEUE', 'ingestion_light'))


def get_stale_job_timeout_seconds() -> int:
    return max(1, int(getattr(settings, 'INGESTION_STALE_JOB_TIMEOUT_SECONDS', 300)))


class WorkloadConcurrencyGate:
    """
    Process-local bounded concurrency limiter separating heavy visual extraction
    jobs from lightweight native Office/text extraction jobs.

    Tracks active & peak concurrency counters per workload class for telemetry
    and automated concurrency tests.
    """

    _lock = threading.RLock()
    _semaphores: Dict[Tuple[str, int], threading.BoundedSemaphore] = {}
    _active: Dict[str, int] = {'visual': 0, 'lightweight': 0}
    _peak: Dict[str, int] = {'visual': 0, 'lightweight': 0}

    @classmethod
    def _get_semaphore(cls, workload_class: str, limit: Optional[int] = None) -> Tuple[str, int, threading.BoundedSemaphore]:
        wcls = 'visual' if workload_class.lower() == 'visual' else 'lightweight'
        eff_limit = max(1, limit if limit is not None else get_workload_concurrency_limit(wcls))
        with cls._lock:
            key = (wcls, eff_limit)
            sem = cls._semaphores.get(key)
            if sem is None:
                sem = threading.BoundedSemaphore(eff_limit)
                cls._semaphores[key] = sem
            return wcls, eff_limit, sem

    @classmethod
    @contextmanager
    def acquire(cls, workload_class: str, limit: Optional[int] = None, timeout: Optional[float] = None):
        wcls, eff_limit, sem = cls._get_semaphore(workload_class, limit=limit)
        acquired = sem.acquire(timeout=timeout) if timeout is not None else sem.acquire()
        if not acquired:
            raise TimeoutError(f"Timed out waiting for '{wcls}' ingestion slot (limit={eff_limit}).")
        with cls._lock:
            cls._active[wcls] = cls._active.get(wcls, 0) + 1
            if cls._active[wcls] > cls._peak.get(wcls, 0):
                cls._peak[wcls] = cls._active[wcls]
        try:
            yield {'workload_class': wcls, 'limit': eff_limit}
        finally:
            with cls._lock:
                cls._active[wcls] = max(0, cls._active.get(wcls, 0) - 1)
            sem.release()

    @classmethod
    def stats(cls) -> Dict[str, Any]:
        with cls._lock:
            from apps.ingestion.pipeline.runtime import GLOBAL_VISUAL_METRICS, get_runtime_cpu_config

            return {
                'active': dict(cls._active),
                'peak': dict(cls._peak),
                'limits': {
                    'visual': get_workload_concurrency_limit('visual'),
                    'lightweight': get_workload_concurrency_limit('lightweight'),
                },
                'runtime_cpu_config': get_runtime_cpu_config(),
                'visual_metrics': GLOBAL_VISUAL_METRICS.snapshot(),
            }

    @classmethod
    def reset_stats(cls) -> None:
        with cls._lock:
            cls._active = {'visual': 0, 'lightweight': 0}
            cls._peak = {'visual': 0, 'lightweight': 0}
            cls._semaphores.clear()


def compute_idempotency_key(
    organization_id: Any,
    workspace_id: Any,
    file_hash: str,
    version_number: int = 1,
) -> str:
    raw = f"{organization_id}:{workspace_id}:{file_hash}:{version_number}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def purge_unsettled_partial_state(
    doc: SourceDocument,
    reset_status: Optional[str] = 'failed',
    force: bool = False,
) -> Dict[str, Any]:
    """
    Removes incomplete/partial vectors, chunks, and pages for a document that has
    NOT reached settled 'ready' publication (or forcibly when aborting/recovering an
    unready job mid-flight), ensuring partially extracted content is never published.
    """
    if doc.status == 'ready' and not force:
        return {'skipped': True, 'reason': 'already_ready'}

    deleted_vectors = False
    try:
        vstore = QdrantVectorStore()
        vstore.delete_document_chunks('lore_chunks', str(doc.id))
        deleted_vectors = True
    except Exception as ex:
        logger.warning(f"Could not purge Qdrant vectors for doc {doc.id}: {ex}")

    deleted_chunks = 0
    try:
        deleted_chunks, _ = DocumentChunk.objects.filter(document=doc).delete()
    except Exception as ex:
        logger.warning(f"Could not purge DocumentChunk rows for doc {doc.id}: {ex}")

    deleted_pages = 0
    try:
        deleted_pages, _ = DocumentPage.objects.filter(document=doc).delete()
    except Exception as ex:
        logger.warning(f"Could not purge DocumentPage rows for doc {doc.id}: {ex}")

    if reset_status and doc.status != reset_status:
        doc.status = reset_status
        doc.save(update_fields=['status'])

    return {
        'skipped': False,
        'deleted_vectors': deleted_vectors,
        'deleted_chunks': deleted_chunks,
        'deleted_pages': deleted_pages,
    }


def sync_batch_status(batch_id: Any) -> Optional[IngestionBatch]:
    if not batch_id:
        return None
    with transaction.atomic():
        batch = IngestionBatch.objects.select_for_update().filter(id=batch_id).first()
        if batch is None:
            return None

        jobs = list(IngestionJob.objects.filter(batch=batch).values_list('status', 'workload_class'))
        meta = dict(batch.metadata or {})
        pre_failed = int(meta.get('validation_failed_count', 0) or 0)
        skipped_dupes = int(meta.get('skipped_duplicate_count', batch.skipped_duplicate_count or 0) or 0)

        completed = sum(1 for st, _ in jobs if st == 'ready')
        failed = sum(1 for st, _ in jobs if st == 'failed') + pre_failed
        needs_review = sum(1 for st, _ in jobs if st == 'needs_review')
        quarantined = sum(1 for st, _ in jobs if st == 'quarantined')
        cancelled = sum(1 for st, _ in jobs if st == 'cancelled')
        queued = sum(1 for st, _ in jobs if st == 'queued')
        running = sum(1 for st, _ in jobs if st in ACTIVE_JOB_STATUSES)

        visual_count = sum(1 for _, wc in jobs if wc == 'visual')
        lightweight_count = sum(1 for _, wc in jobs if wc != 'visual')

        batch.visual_jobs_count = visual_count
        batch.lightweight_jobs_count = lightweight_count
        batch.completed_count = completed
        batch.failed_count = failed
        batch.needs_review_count = needs_review
        batch.quarantined_count = quarantined
        batch.cancelled_count = cancelled
        batch.skipped_duplicate_count = skipped_dupes

        if running > 0 or queued > 0:
            batch.status = 'processing' if (running > 0 or completed + failed + needs_review + quarantined + cancelled > 0) else 'queued'
            batch.completed_at = None
        else:
            batch.completed_at = batch.completed_at or timezone.now()
            total_settled = completed + skipped_dupes
            if cancelled > 0 and total_settled == 0 and failed == 0 and needs_review == 0 and quarantined == 0:
                batch.status = 'cancelled'
            elif failed > 0 or quarantined > 0 or needs_review > 0 or cancelled > 0:
                batch.status = 'partial_success' if (total_settled > 0 or needs_review > 0) else 'failed'
            elif total_settled > 0:
                batch.status = 'completed'
            else:
                batch.status = 'failed'

        batch.save()
        return batch


def dispatch_job_to_celery(job: IngestionJob) -> Dict[str, Any]:
    """
    Routes an IngestionJob to either the heavy visual Celery task/queue or the
    lightweight native parser Celery task/queue.
    """
    from apps.ingestion.tasks import (
        process_lightweight_document_job,
        process_visual_document_job,
    )

    workload_class = job.workload_class or classify_ingestion_workload(
        doc_type=job.document.document_type,
        filename=job.document.original_filename,
        mime_type=getattr(job.document, 'mime_type', ''),
    )
    queue_name = job.queue_name or get_workload_queue_name(workload_class)

    updates: List[str] = []
    if job.workload_class != workload_class:
        job.workload_class = workload_class
        updates.append('workload_class')
    if job.queue_name != queue_name:
        job.queue_name = queue_name
        updates.append('queue_name')
    if updates:
        job.save(update_fields=updates)

    task_obj: Any = process_visual_document_job if workload_class == 'visual' else process_lightweight_document_job
    async_result = task_obj.apply_async(args=[str(job.id)], queue=queue_name)
    return {
        'job_id': str(job.id),
        'task_id': getattr(async_result, 'id', None),
        'workload_class': workload_class,
        'queue_name': queue_name,
    }


def dispatch_pending_batch_jobs(batch_id: Any) -> Dict[str, Any]:
    """
    Refills Celery queues for queued jobs in a batch while respecting the
    separate concurrency caps for visual and lightweight workloads.
    """
    dispatched: List[Dict[str, Any]] = []
    with transaction.atomic():
        batch = IngestionBatch.objects.select_for_update().filter(id=batch_id).first()
        if batch is None or batch.status == 'cancelled':
            return {'dispatched': [], 'batch_status': getattr(batch, 'status', None)}

        visual_limit = max(1, batch.max_concurrent_visual or get_workload_concurrency_limit('visual'))
        light_limit = max(1, batch.max_concurrent_lightweight or get_workload_concurrency_limit('lightweight'))

        batch_jobs = IngestionJob.objects.filter(batch=batch)
        active_visual = batch_jobs.filter(
            workload_class='visual',
            status__in=ACTIVE_JOB_STATUSES,
        ).count()
        active_light = batch_jobs.filter(
            workload_class='lightweight',
            status__in=ACTIVE_JOB_STATUSES,
        ).count()

        visual_slots = max(0, visual_limit - active_visual)
        light_slots = max(0, light_limit - active_light)

        jobs_to_dispatch: List[IngestionJob] = []
        if visual_slots > 0:
            jobs_to_dispatch.extend(
                list(
                    batch_jobs.select_related('document')
                    .filter(workload_class='visual', status='queued', is_cancellation_requested=False)
                    .order_by('created_at')[:visual_slots]
                )
            )
        if light_slots > 0:
            jobs_to_dispatch.extend(
                list(
                    batch_jobs.select_related('document')
                    .filter(workload_class='lightweight', status='queued', is_cancellation_requested=False)
                    .order_by('created_at')[:light_slots]
                )
            )

    for job in jobs_to_dispatch:
        dispatched.append(dispatch_job_to_celery(job))

    return {'dispatched': dispatched, 'count': len(dispatched)}


class IngestionBatchService:
    """
    Coordinates batch uploads up to INGESTION_MAX_BATCH_FILES (100), enforcing:
    - Organization & workspace isolation
    - Per-document validation & failure isolation
    - Visual vs lightweight routing (only PDF/image through visual extractor)
    - Controlled concurrency per workload class
    - Duplicate detection & idempotency within organization+workspace
    - Cooperative cancellation & worker-restart recovery
    """

    @classmethod
    def validate_batch_size(cls, count: int) -> None:
        max_files = get_max_batch_files()
        if count <= 0:
            raise ValidationError("At least one file is required for batch ingestion.")
        if count > max_files:
            raise ValidationError(
                f"Batch size {count} exceeds maximum supported limit of {max_files} files per batch."
            )

    @classmethod
    def find_existing_workspace_document(
        cls,
        organization,
        workspace,
        file_hash: str,
    ) -> Optional[SourceDocument]:
        if not file_hash:
            return None
        return (
            SourceDocument.objects.filter(
                organization=organization,
                workspace=workspace,
                file_hash=file_hash,
                status__in=('ready', 'approved', 'needs_review'),
            )
            .order_by('-created_at')
            .first()
        )

    @classmethod
    def create_and_dispatch_batch(
        cls,
        files: Iterable[Any],
        workspace,
        user,
        collection=None,
        authority_level: int = 3,
        description: str = '',
        titles_map: Optional[Any] = None,
        base_title: Optional[str] = None,
        deduplicate: bool = True,
        eager: Optional[bool] = None,
    ) -> Dict[str, Any]:
        file_list = list(files)
        cls.validate_batch_size(len(file_list))

        visual_limit = get_workload_concurrency_limit('visual')
        light_limit = get_workload_concurrency_limit('lightweight')
        effective_eager = (
            getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True)
            if eager is None
            else eager
        )

        batch = IngestionBatch.objects.create(
            organization=workspace.organization,
            workspace=workspace,
            created_by=user if getattr(user, 'is_authenticated', False) else None,
            status='queued',
            total_files=len(file_list),
            max_concurrent_visual=visual_limit,
            max_concurrent_lightweight=light_limit,
            metadata={'validation_failed_count': 0, 'skipped_duplicate_count': 0},
        )

        from apps.subscriptions.services import QuotaEnforcementService

        successful_entries: List[Dict[str, Any]] = []
        failed_entries: List[Dict[str, Any]] = []
        created_jobs: List[IngestionJob] = []
        seen_hashes_in_batch: Dict[str, SourceDocument] = {}
        validation_failed_count = 0
        skipped_duplicate_count = 0

        for idx, file_obj in enumerate(file_list):
            if isinstance(titles_map, dict) and file_obj.name in titles_map:
                file_title = titles_map[file_obj.name]
            elif isinstance(titles_map, list) and idx < len(titles_map):
                file_title = titles_map[idx]
            elif base_title and len(file_list) == 1:
                file_title = base_title
            elif base_title:
                file_title = f"{base_title} - {file_obj.name}"
            else:
                file_title = os.path.splitext(file_obj.name)[0]

            try:
                sec_meta = StorageSecurityService.inspect_and_validate(file_obj)
                file_hash = sec_meta['file_hash']

                # Idempotency / duplicate check strictly within (organization, workspace)
                existing_doc = None
                if deduplicate:
                    existing_doc = seen_hashes_in_batch.get(file_hash) or cls.find_existing_workspace_document(
                        organization=workspace.organization,
                        workspace=workspace,
                        file_hash=file_hash,
                    )

                if existing_doc is not None:
                    skipped_duplicate_count += 1
                    existing_job = IngestionJob.objects.filter(document=existing_doc).order_by('-created_at').first()
                    successful_entries.append({
                        'document_obj': existing_doc,
                        'job_obj': existing_job,
                        'duplicate_of': str(existing_doc.id),
                        'deduplicated': True,
                        'workload_class': classify_ingestion_workload(
                            doc_type=existing_doc.document_type,
                            filename=existing_doc.original_filename,
                            mime_type=existing_doc.mime_type,
                        ),
                    })
                    continue

                QuotaEnforcementService.check_upload_quota(workspace.organization, sec_meta['file_size'])

                workload_class = classify_ingestion_workload(
                    doc_type=sec_meta['document_type'],
                    filename=file_obj.name,
                    mime_type=sec_meta['mime_type'],
                )
                requires_visual, routing_reason = needs_visual_extraction(
                    doc_type=sec_meta['document_type'],
                    filename=file_obj.name,
                    mime_type=sec_meta['mime_type'],
                )
                queue_name = get_workload_queue_name(workload_class)
                idempotency_key = compute_idempotency_key(
                    organization_id=workspace.organization_id,
                    workspace_id=workspace.id,
                    file_hash=file_hash,
                    version_number=1,
                )

                doc = SourceDocument.objects.create(
                    organization=workspace.organization,
                    workspace=workspace,
                    collection=collection,
                    owner=user if getattr(user, 'is_authenticated', False) else None,
                    title=file_title or file_obj.name,
                    description=description,
                    original_filename=file_obj.name,
                    mime_type=sec_meta['mime_type'],
                    file_size=sec_meta['file_size'],
                    file_hash=file_hash,
                    file_obj=file_obj,
                    document_type=sec_meta['document_type'],
                    authority_level=authority_level,
                    status='queued',
                )
                QuotaEnforcementService.record_upload(workspace.organization, workspace, sec_meta['file_size'])

                DocumentVersion.objects.create(
                    document=doc,
                    version_number=1,
                    file_hash=file_hash,
                    file_obj=doc.file_obj,
                    change_summary='Initial upload',
                    is_current=True,
                )

                job = IngestionJob.objects.create(
                    document=doc,
                    organization=workspace.organization,
                    workspace=workspace,
                    batch=batch,
                    status='queued',
                    current_stage='inspection',
                    workload_class=workload_class,
                    queue_name=queue_name,
                    idempotency_key=idempotency_key,
                    stage_timings={
                        'routing': {
                            'workload_class': workload_class,
                            'queue_name': queue_name,
                            'requires_visual_extraction': requires_visual,
                            'routing_reason': routing_reason,
                        }
                    },
                )

                AuditEvent.objects.create(
                    organization=workspace.organization,
                    workspace=workspace,
                    user=user if getattr(user, 'is_authenticated', False) else None,
                    event_type='document_uploaded',
                    target_type='document',
                    target_id=str(doc.id),
                    details={
                        'filename': file_obj.name,
                        'size': sec_meta['file_size'],
                        'sha256': file_hash,
                        'batch_id': str(batch.id),
                        'workload_class': workload_class,
                        'queue_name': queue_name,
                    },
                )

                if deduplicate:
                    seen_hashes_in_batch[file_hash] = doc

                created_jobs.append(job)
                successful_entries.append({
                    'document_obj': doc,
                    'job_obj': job,
                    'duplicate_of': None,
                    'deduplicated': False,
                    'workload_class': workload_class,
                })
            except Exception as exc:
                validation_failed_count += 1
                failed_entries.append({
                    'filename': getattr(file_obj, 'name', f'file_{idx}'),
                    'error': str(exc),
                })

        batch.metadata = {
            **(batch.metadata or {}),
            'validation_failed_count': validation_failed_count,
            'skipped_duplicate_count': skipped_duplicate_count,
        }
        batch.skipped_duplicate_count = skipped_duplicate_count
        batch.failed_count = validation_failed_count
        batch.visual_jobs_count = sum(1 for j in created_jobs if j.workload_class == 'visual')
        batch.lightweight_jobs_count = sum(1 for j in created_jobs if j.workload_class == 'lightweight')
        batch.save()

        if created_jobs:
            if effective_eager:
                from apps.ingestion.coordinator import SequentialPipelineCoordinator

                for job in created_jobs:
                    job.refresh_from_db()
                    if job.is_cancellation_requested or job.status == 'cancelled':
                        continue
                    try:
                        with WorkloadConcurrencyGate.acquire(job.workload_class):
                            SequentialPipelineCoordinator.orchestrate_pipeline(
                                str(job.id),
                                raise_exceptions=False,
                            )
                    except Exception as exc:
                        logger.warning(f"Batch eager execution isolated failure on job {job.id}: {exc}")
            else:
                dispatch_pending_batch_jobs(batch.id)

        # Refresh entries after eager or dispatch
        for entry in successful_entries:
            entry['document_obj'].refresh_from_db()
            if entry['job_obj'] is not None:
                entry['job_obj'].refresh_from_db()

        sync_batch_status(batch.id)
        batch.refresh_from_db()

        return {
            'batch': batch,
            'successful': successful_entries,
            'failed': failed_entries,
        }

    @classmethod
    def cancel_job(cls, job: IngestionJob, reason: str = 'Cancelled by user') -> Dict[str, Any]:
        with transaction.atomic():
            locked = IngestionJob.objects.select_for_update().select_related('document').get(id=job.id)
            if locked.status in ('ready', 'failed', 'quarantined', 'needs_review'):
                return {'cancelled': False, 'reason': f'Job already in terminal state {locked.status}', 'status': locked.status}

            now = timezone.now()
            locked.is_cancellation_requested = True
            locked.cancelled_at = locked.cancelled_at or now
            if locked.status == 'queued':
                locked.status = 'cancelled'
                locked.current_stage = 'cancelled'
                locked.completed_at = now
                locked.error_message = reason
                locked.error_category = 'CANCELLED'
                locked.save()
                IngestionPipelineRun.objects.filter(job=locked, status__in=('pending', 'running')).update(
                    status='skipped',
                    error_message=reason,
                    completed_at=now,
                )
                purge_unsettled_partial_state(locked.document, reset_status='failed')
                action_state = 'cancelled_immediately'
            else:
                locked.error_message = reason
                locked.save(update_fields=['is_cancellation_requested', 'cancelled_at', 'error_message', 'updated_at'])
                action_state = 'cancellation_requested'

        if locked.batch_id:
            sync_batch_status(locked.batch_id)

        return {'cancelled': True, 'action': action_state, 'status': locked.status}

    @classmethod
    def cancel_batch(cls, batch: IngestionBatch, reason: str = 'Batch cancelled by user') -> Dict[str, Any]:
        results = []
        for job in IngestionJob.objects.filter(batch=batch).select_related('document').all():
            results.append(cls.cancel_job(job, reason=reason))
        updated_batch = sync_batch_status(batch.id)
        return {
            'batch_id': str(batch.id),
            'status': updated_batch.status if updated_batch else batch.status,
            'results': results,
        }

    @classmethod
    def retry_failed_jobs_in_batch(cls, batch: IngestionBatch, eager: Optional[bool] = None) -> Dict[str, Any]:
        effective_eager = (
            getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True)
            if eager is None
            else eager
        )
        failed_jobs = list(IngestionJob.objects.filter(batch=batch).select_related('document').filter(status='failed'))
        retried_ids: List[str] = []

        for job in failed_jobs:
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
            retried_ids.append(str(job.id))

        if retried_ids:
            if effective_eager:
                from apps.ingestion.coordinator import SequentialPipelineCoordinator

                for jid in retried_ids:
                    j = IngestionJob.objects.get(id=jid)
                    with WorkloadConcurrencyGate.acquire(j.workload_class):
                        SequentialPipelineCoordinator.orchestrate_pipeline(jid, raise_exceptions=False)
            else:
                dispatch_pending_batch_jobs(batch.id)

        updated = sync_batch_status(batch.id)
        return {
            'batch_id': str(batch.id),
            'retried_job_ids': retried_ids,
            'retried_count': len(retried_ids),
            'status': updated.status if updated else batch.status,
        }

    @classmethod
    def recover_stalled_jobs(
        cls,
        timeout_seconds: Optional[int] = None,
        batch_id: Optional[Any] = None,
        organization_id: Optional[Any] = None,
        workspace_id: Optional[Any] = None,
        re_dispatch: bool = True,
        eager: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Worker restart recovery: finds jobs orphaned mid-flight during a worker
        crash (stuck in ACTIVE_JOB_STATUSES with stale heartbeat_at / started_at),
        rolls back any partial/unsettled chunks or vectors so partially extracted
        content is never published as ready, and safely re-queues up to max_retries.
        """
        eff_timeout = max(1, timeout_seconds if timeout_seconds is not None else get_stale_job_timeout_seconds())
        cutoff = timezone.now() - timedelta(seconds=eff_timeout)
        effective_eager = (
            getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True)
            if eager is None
            else eager
        )

        qs = IngestionJob.objects.select_related('document').filter(status__in=ACTIVE_JOB_STATUSES)
        if batch_id is not None:
            qs = qs.filter(batch_id=batch_id)
        if organization_id is not None:
            qs = qs.filter(organization_id=organization_id)
        if workspace_id is not None:
            qs = qs.filter(workspace_id=workspace_id)

        recovered_ids: List[str] = []
        cancelled_ids: List[str] = []
        exhausted_ids: List[str] = []
        impacted_batches = set()

        for job in qs:
            last_beat = job.heartbeat_at or job.started_at or job.updated_at or job.created_at
            if last_beat > cutoff:
                continue

            with transaction.atomic():
                locked = IngestionJob.objects.select_for_update().select_related('document').get(id=job.id)
                if locked.status not in ACTIVE_JOB_STATUSES:
                    continue

                if locked.batch_id:
                    impacted_batches.add(locked.batch_id)

                if locked.is_cancellation_requested:
                    purge_unsettled_partial_state(locked.document, reset_status='failed', force=True)
                    locked.status = 'cancelled'
                    locked.current_stage = 'cancelled'
                    locked.completed_at = timezone.now()
                    locked.worker_id = ''
                    locked.error_category = 'CANCELLED_ON_RECOVERY'
                    locked.save()
                    cancelled_ids.append(str(locked.id))
                    continue

                if locked.attempt_count <= locked.max_retries:
                    purge_unsettled_partial_state(locked.document, reset_status='queued', force=True)
                    locked.status = 'queued'
                    locked.current_stage = 'inspection'
                    locked.attempt_count += 1
                    locked.worker_id = ''
                    locked.heartbeat_at = None
                    locked.error_message = 'Recovered stalled job after worker restart.'
                    locked.error_category = 'WORKER_RESTART_RECOVERED'
                    locked.save()
                    recovered_ids.append(str(locked.id))
                else:
                    purge_unsettled_partial_state(locked.document, reset_status='failed', force=True)
                    locked.status = 'failed'
                    locked.current_stage = 'failed'
                    locked.completed_at = timezone.now()
                    locked.worker_id = ''
                    locked.error_message = 'Max retries exceeded after worker loss.'
                    locked.error_category = 'WORKER_LOSS_MAX_RETRIES'
                    locked.save()
                    exhausted_ids.append(str(locked.id))

        if re_dispatch and recovered_ids:
            if effective_eager:
                from apps.ingestion.coordinator import SequentialPipelineCoordinator

                for jid in recovered_ids:
                    j = IngestionJob.objects.get(id=jid)
                    with WorkloadConcurrencyGate.acquire(j.workload_class):
                        SequentialPipelineCoordinator.orchestrate_pipeline(jid, raise_exceptions=False)
            else:
                for jid in recovered_ids:
                    dispatch_job_to_celery(IngestionJob.objects.select_related('document').get(id=jid))

        for bid in impacted_batches:
            sync_batch_status(bid)

        return {
            'recovered_count': len(recovered_ids),
            'recovered_job_ids': recovered_ids,
            'cancelled_count': len(cancelled_ids),
            'exhausted_count': len(exhausted_ids),
        }


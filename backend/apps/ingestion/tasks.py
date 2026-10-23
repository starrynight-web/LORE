import time
import logging
from django.utils import timezone
from celery import shared_task
from django.db import transaction

from .models import IngestionJob
from apps.sources.models import SourceDocument, DocumentPage, DocumentVersion
from apps.knowledge.models import DocumentChunk
from apps.knowledge.chunking import StructureAwareChunker
from apps.retrieval.vector_store import QdrantVectorStore
from apps.retrieval.embeddings import get_embedding_adapter
from apps.audit.models import AuditEvent
from apps.subscriptions.services import QuotaEnforcementService
from .pipeline.extractors import UnifiedDocumentExtractor

logger = logging.getLogger(__name__)

def process_ingestion_pipeline(job_id: str, raise_exceptions: bool = False):
    """
    Synchronous / asynchronous execution of the complete document ingestion pipeline.
    Executes the Six-Stage Settlement Gate (lore.md §7):
    S1: Structure & Input Validation
    S2: Security Screening (Prompt injection, leaked secrets)
    S3: Extraction, Groundedness & Quality Validation (Per-page confidence, substance)
    S4: Deduplication & Version Identity (SHA-256 hash, idempotent reprocessing, immutable DocumentVersion)
    S5: Conflict Pre-Scan (Relational ConflictRecord pre-scan vs workspace documents)
    S6: Staged Merge, Smoke Test & Rollback (Atomic vector indexing, retrieval smoke test, auto-rollback, publication gate)
    """
    from apps.ingestion.settlement import SettlementGateCoordinator, SettlementReasonCode

    job = IngestionJob.objects.select_related('document', 'document__workspace', 'document__organization').get(id=job_id)
    doc = job.document

    try:
        job.started_at = timezone.now()
        job.status = 'extracting'
        job.current_stage = 'extraction'
        job.save()

        # Immutable Version Tracking
        doc_version, _ = DocumentVersion.objects.get_or_create(
            document=doc,
            version_number=doc.current_version_number,
            defaults={
                'file_hash': doc.file_hash,
                'file_obj': doc.file_obj,
                'is_current': True
            }
        )

        # Determine if approval is explicitly required
        require_approval = False
        if job.stage_timings and job.stage_timings.get('require_approval'):
            require_approval = True
        elif getattr(doc, 'require_approval', False):
            require_approval = True

        # Execute 6-Stage Settlement Gate
        settlement = SettlementGateCoordinator.execute_settlement(
            doc=doc,
            doc_version=doc_version,
            require_approval=require_approval
        )

        job.status = settlement["status"]
        job.current_stage = 'completed' if settlement["status"] in ('ready', 'needs_review', 'quarantined') else 'failed'
        timings = dict(settlement.get("stages", {}))
        if "stage_3_extraction" in timings:
            timings["extraction_ms"] = timings["stage_3_extraction"].get("duration_ms", 0)
        if "stage_6_merge" in timings:
            s6_details = timings["stage_6_merge"].get("details", {})
            timings["chunking_ms"] = s6_details.get("chunking_ms", timings["stage_6_merge"].get("duration_ms", 0))
            timings["embedding_ms"] = s6_details.get("embedding_ms", 0)
            timings["indexing_ms"] = s6_details.get("indexing_ms", 0)
        job.stage_timings = timings
        job.completed_at = timezone.now()

        # Check for specific failure categories
        if settlement["status"] == "failed":
            s4_reasons = settlement.get("stages", {}).get("stage_4_dedup", {}).get("reason_codes", [])
            if SettlementReasonCode.S4_STALE_WORKER_ABORTED.value in s4_reasons:
                job.error_category = 'STALE_VERSION_OVERWRITE_PREVENTED'
                job.error_message = (
                    f"Aborted stale job version {doc_version.version_number}; "
                    f"current document version is {SourceDocument.objects.get(id=doc.id).current_version_number}."
                )
                job.save()
                AuditEvent.objects.create(
                    organization=doc.organization,
                    workspace=doc.workspace,
                    event_type='stale_worker_aborted',
                    target_type='document',
                    target_id=str(doc.id),
                    details={
                        'job_version': doc_version.version_number,
                        'current_version': SourceDocument.objects.get(id=doc.id).current_version_number,
                    }
                )
            else:
                failed_stage = settlement.get("failed_stage", 0)
                stage_key = f"stage_{failed_stage}"
                stage_details = settlement.get("stages", {}).get(stage_key, {}).get("details", {})
                job.error_message = stage_details.get("error", f"Settlement failed at stage {failed_stage}.")
                job.error_category = f"SETTLEMENT_STAGE_{failed_stage}_FAILED"
                job.save()

            if raise_exceptions:
                raise RuntimeError(job.error_message)
            return

        job.save()

    except Exception as e:
        logger.exception(f"Ingestion job {job_id} failed: {e}")
        try:
            job = IngestionJob.objects.get(id=job_id)
            job.status = 'failed'
            job.current_stage = 'failed'
            job.error_message = str(e)
            job.error_category = 'pipeline_exception'
            job.save()
            doc.status = 'failed'
            doc.save(update_fields=['status'])
            AuditEvent.objects.create(
                organization=doc.organization,
                workspace=doc.workspace,
                event_type='ingestion_failed',
                target_type='document',
                target_id=str(doc.id),
                details={'error': str(e), 'stage': job.current_stage}
            )
        except Exception as audit_err:
            logger.error(f"Error handling failure for job {job_id}: {audit_err}")

        if raise_exceptions:
            raise

class TransientIngestionError(Exception):
    """Temporary network or connection error that warrants a retry."""
    pass

class PermanentIngestionError(Exception):
    """Unrecoverable data or format error that should not be retried."""
    pass

@shared_task(bind=True, max_retries=3)
def process_document_job(self, job_id: str):
    """
    Celery task wrapper with transient vs permanent error classification and exponential backoff.
    """
    try:
        process_ingestion_pipeline(job_id, raise_exceptions=True)
    except Exception as exc:
        transient_types = (ConnectionError, TimeoutError, OSError, TransientIngestionError)
        is_transient = isinstance(exc, transient_types) or any(
            err_term in str(exc).lower() for err_term in ('connection', 'timeout', 'temporary', 'retry')
        )
        if isinstance(exc, (ValueError, KeyError, TypeError, FileNotFoundError, PermanentIngestionError)):
            is_transient = False

        if is_transient and self.request.retries < self.max_retries:
            backoff_seconds = (2 ** self.request.retries) * 5
            logger.warning(
                f"Ingestion job {job_id} encountered transient error: {exc}. "
                f"Retrying in {backoff_seconds}s (attempt {self.request.retries + 1}/{self.max_retries})."
            )
            try:
                job = IngestionJob.objects.get(id=job_id)
                job.attempt_count = self.request.retries + 2
                job.save(update_fields=['attempt_count'])
            except Exception:
                pass
            raise self.retry(exc=exc, countdown=backoff_seconds)
        else:
            logger.error(f"Ingestion job {job_id} permanently failed: {exc}")
            raise exc


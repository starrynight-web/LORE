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
    Synchronous / asynchronous execution of the complete 4-run sequential ingestion pipeline:
    Run 1: Initial Ingestion & Indexing (Settlement Gate S1-S6)
    Run 2: Quality Validation & Refinement (DocumentQualityService)
    Run 3: Retrieval Optimization (Retrievability & Evaluation)
    Run 4: Evaluation, Verification, and Improvement Decision
    """
    from apps.ingestion.coordinator import SequentialPipelineCoordinator
    return SequentialPipelineCoordinator.orchestrate_pipeline(job_id, raise_exceptions=raise_exceptions)

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


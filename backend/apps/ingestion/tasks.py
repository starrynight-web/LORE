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
    Handles extraction, OCR, normalization, chunking, embedding, vector indexing, and governance.
    Includes idempotency safeguards, stale worker protection, and cache invalidation.
    """
    job = IngestionJob.objects.select_related('document', 'document__workspace', 'document__organization').get(id=job_id)
    doc = job.document
    timings = {}

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

        # ---------------- Stage 1: Extraction & OCR ----------------
        t0 = time.time()
        file_path = doc.file_obj.path
        extractor = UnifiedDocumentExtractor()
        pages_data = extractor.extract_document(
            file_path_or_bytes=file_path,
            doc_type=doc.document_type,
            filename=doc.original_filename
        )
        t_extract = int((time.time() - t0) * 1000)
        timings['extraction_ms'] = t_extract

        # Save pages to database tied to document_version
        with transaction.atomic():
            DocumentPage.objects.filter(document=doc).delete()
            pages_to_create = []
            for p in pages_data:
                pages_to_create.append(DocumentPage(
                    document=doc,
                    document_version=doc_version,
                    page_number=p['page_number'],
                    text=p['text'],
                    confidence=p.get('confidence', 1.0),
                    words_count=p.get('words_count', 0),
                    width=p.get('width', 0.0),
                    height=p.get('height', 0.0),
                    extraction_type=p.get('extraction_type', 'digital'),
                    engine=p.get('engine', 'native'),
                    engine_version=p.get('engine_version', ''),
                    is_repaired=p.get('is_repaired', False),
                    bounding_boxes=p.get('bounding_boxes', [])
                ))
            DocumentPage.objects.bulk_create(pages_to_create)

            # Update document page stats and average OCR confidence
            avg_conf = (
                sum(p.get('confidence', 1.0) for p in pages_data) / max(len(pages_data), 1)
            )
            doc.page_count = len(pages_data)
            doc.ocr_confidence = round(avg_conf, 3)
            doc.status = 'normalizing'
            doc.save(update_fields=['page_count', 'ocr_confidence', 'status'])

        # ---------------- Stage 2: Normalization ----------------
        t0 = time.time()
        job.status = 'normalizing'
        job.current_stage = 'normalization'
        job.save()
        t_norm = int((time.time() - t0) * 1000)
        timings['normalization_ms'] = t_norm

        # ---------------- Stage 3: Structure-Aware Chunking ----------------
        t0 = time.time()
        job.status = 'chunking'
        job.current_stage = 'chunking'
        job.save()

        raw_chunks = StructureAwareChunker.chunk_document_pages(
            doc_id=str(doc.id),
            doc_title=doc.title,
            org_name=doc.organization.name,
            ws_name=doc.workspace.name,
            authority_rank=doc.authority_level,
            pages_data=pages_data
        )

        with transaction.atomic():
            DocumentChunk.objects.filter(document=doc).delete()
            created_chunks = []
            for c in raw_chunks:
                created_chunks.append(DocumentChunk(
                    organization=doc.organization,
                    workspace=doc.workspace,
                    document=doc,
                    document_version=doc_version,
                    chunk_index=c['chunk_index'],
                    text=c['text'],
                    contextual_header=c['contextual_header'],
                    page_number=c['page_number'],
                    heading_path=c['heading_path'],
                    char_offset_start=c['char_offset_start'],
                    char_offset_end=c['char_offset_end'],
                    token_count=c['token_count'],
                ))
            DocumentChunk.objects.bulk_create(created_chunks)

        t_chunk = int((time.time() - t0) * 1000)
        timings['chunking_ms'] = t_chunk

        # ---------------- Stage 4: Embeddings Generation ----------------
        t0 = time.time()
        job.status = 'embedding'
        job.current_stage = 'embedding'
        job.save()

        saved_chunks = list(DocumentChunk.objects.filter(document=doc).order_by('chunk_index'))
        embed_texts = [f"{c.contextual_header}\n---\n{c.text}" for c in saved_chunks]
        embedder = get_embedding_adapter()
        vectors = embedder.embed_batch(embed_texts)
        t_embed = int((time.time() - t0) * 1000)
        timings['embedding_ms'] = t_embed

        # ---------------- Stage 5: Vector Indexing (Qdrant) ----------------
        t0 = time.time()
        job.status = 'indexing'
        job.current_stage = 'indexing'
        job.save()

        vstore = QdrantVectorStore()
        # Idempotency: Purge any existing vectors for this document prior to upserting
        try:
            vstore.delete_document_chunks("lore_chunks", str(doc.id))
        except Exception as e:
            logger.warning(f"Could not purge existing chunks for doc {doc.id}: {e}")

        ids = [str(c.id) for c in saved_chunks]
        payloads = [
            {
                'chunk_id': str(c.id),
                'document_id': str(doc.id),
                'document_version': doc_version.version_number,
                'document_title': doc.title,
                'organization_id': str(doc.organization.id),
                'workspace_id': str(doc.workspace.id),
                'collection_id': str(doc.collection.id) if doc.collection else "",
                'page_number': c.page_number,
                'heading_path': c.heading_path,
                'authority_level': doc.authority_level,
                'text': c.text[:300]
            }
            for c in saved_chunks
        ]

        vstore.upsert_chunks(
            collection_name="lore_chunks",
            vectors=vectors,
            payloads=payloads,
            ids=ids
        )

        for i, c in enumerate(saved_chunks):
            c.vector_id = ids[i]
            c.save(update_fields=['vector_id'])

        t_index = int((time.time() - t0) * 1000)
        timings['indexing_ms'] = t_index

        # ---------------- Stage 6: Final Verification & Governance ----------------
        job.stage_timings = timings
        job.completed_at = timezone.now()

        # Stale Worker Protection: Verify no newer version was created during processing
        fresh_doc = SourceDocument.objects.get(id=doc.id)
        if fresh_doc.current_version_number > doc_version.version_number:
            logger.warning(
                f"Stale worker detected for doc {doc.id}: current version {fresh_doc.current_version_number} "
                f"> job version {doc_version.version_number}. Aborting."
            )
            job.status = 'failed'
            job.current_stage = 'failed'
            job.error_category = 'STALE_VERSION_OVERWRITE_PREVENTED'
            job.error_message = (
                f"Aborted stale job version {doc_version.version_number}; "
                f"current document version is {fresh_doc.current_version_number}."
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
                    'current_version': fresh_doc.current_version_number,
                }
            )
            return

        # Follow ocr.md Rule X001: low confidence (< 70%) routes to review queue
        if doc.ocr_confidence < 0.70 and doc.document_type in ('pdf', 'image'):
            doc.status = 'needs_review'
            job.status = 'needs_review'
            job.current_stage = 'completed'
            job.save()
            doc.save(update_fields=['status'])
            AuditEvent.objects.create(
                organization=doc.organization,
                workspace=doc.workspace,
                event_type='item_quarantined',
                target_type='document',
                target_id=str(doc.id),
                details={'reason': f'Low OCR confidence: {doc.ocr_confidence:.2f}'}
            )
        else:
            doc.status = 'ready'
            job.status = 'ready'
            job.current_stage = 'completed'
            job.save()
            doc.save(update_fields=['status'])
            AuditEvent.objects.create(
                organization=doc.organization,
                workspace=doc.workspace,
                event_type='ingestion_completed',
                target_type='document',
                target_id=str(doc.id),
                details={'chunks_indexed': len(saved_chunks), 'timings': timings}
            )

        # Invalidate workspace/document query cache so newly published content is immediately retrievable
        try:
            from apps.retrieval.cache import TenantSafeCacheService
            TenantSafeCacheService.invalidate_document(str(doc.workspace.id), str(doc.id))
        except Exception as ce:
            logger.warning(f"Failed to invalidate cache for doc {doc.id}: {ce}")

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


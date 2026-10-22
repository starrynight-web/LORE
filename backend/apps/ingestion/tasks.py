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

def process_ingestion_pipeline(job_id: str):
    """
    Synchronous / asynchronous execution of the complete document ingestion pipeline.
    Handles extraction, OCR, normalization, chunking, embedding, vector indexing, and governance.
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
            doc.save()

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

        # Follow ocr.md Rule X001: low confidence (< 70%) routes to review queue
        if doc.ocr_confidence < 0.70 and doc.document_type in ('pdf', 'image'):
            doc.status = 'needs_review'
            job.status = 'needs_review'
            job.current_stage = 'completed'
            job.save()
            doc.save()
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
            doc.save()
            AuditEvent.objects.create(
                organization=doc.organization,
                workspace=doc.workspace,
                event_type='ingestion_completed',
                target_type='document',
                target_id=str(doc.id),
                details={'chunks_indexed': len(saved_chunks), 'timings': timings}
            )

    except Exception as e:
        logger.exception(f"Ingestion job {job_id} failed: {e}")
        job.status = 'failed'
        job.current_stage = 'failed'
        job.error_message = str(e)
        job.error_category = 'pipeline_exception'
        job.save()
        doc.status = 'failed'
        doc.save()

@shared_task(bind=True, max_retries=3)
def process_document_job(self, job_id: str):
    """Celery task wrapper."""
    process_ingestion_pipeline(job_id)

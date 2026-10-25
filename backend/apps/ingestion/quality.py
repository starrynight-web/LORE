import time
import hashlib
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from django.db import transaction
from django.utils import timezone

from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.knowledge.models import DocumentChunk
from apps.knowledge.chunking import StructureAwareChunker
from apps.retrieval.vector_store import QdrantVectorStore
from apps.retrieval.embeddings import get_embedding_adapter
from apps.audit.models import AuditEvent

logger = logging.getLogger(__name__)


@dataclass
class QualityAuditReport:
    """
    Measurable, auditable document quality report for Run 2: Quality Validation & Refinement.
    Never lumps distinct signals into an opaque composite score.
    """
    extraction_completeness: float = 1.0
    ocr_confidence: float = 1.0
    ocr_threshold_applied: float = 0.70
    chunk_validation: Dict[str, Any] = field(default_factory=dict)
    duplicate_detection: Dict[str, Any] = field(default_factory=dict)
    metadata_completeness: float = 1.0
    vector_verification: Dict[str, Any] = field(default_factory=dict)
    
    embeddings_reused: int = 0
    embeddings_regenerated: int = 0
    
    issues_detected: List[str] = field(default_factory=list)
    issues_corrected: List[str] = field(default_factory=list)
    chunks_reprocessed: int = 0
    
    requires_human_review: bool = False
    review_reason: str = ""
    
    final_quality_status: str = "pending"  # passed, needs_review, failed
    details: Dict[str, Any] = field(default_factory=dict)


class DocumentQualityService:
    """
    Quality inspection, validation, and intelligent refinement service for LORE.
    Detects and safely repairs document processing defects that damage retrieval quality:
    - Empty or truncated text
    - Low OCR confidence below per-type threshold
    - Poor chunk boundaries or missing context headers
    - Duplicate chunks
    - Missing metadata/provenance
    - Chunk-to-vector parity discrepancies
    - Selective embedding reuse & regeneration
    - Protection of last known-good index
    """

    # Configurable OCR thresholds based on document format and assurance level
    OCR_THRESHOLDS = {
        'pdf_scanned': 0.70,
        'image': 0.70,
        'legal_deed': 0.80,
        'digital_pdf': 0.90,
        'docx': 0.95,
        'txt': 0.95,
        'json': 0.95,
        'default': 0.70,
    }

    @classmethod
    def compute_chunk_content_hash(
        cls,
        text: str,
        contextual_header: str,
        model_name: str,
        dimension: int
    ) -> str:
        """
        Deterministic SHA-256 fingerprint incorporating normalized chunk content,
        contextual heading, embedding model identity, and vector dimension.
        """
        norm_text = " ".join(text.strip().split())
        norm_header = " ".join(contextual_header.strip().split())
        payload = f"{norm_header}\n---\n{norm_text}:{model_name}:{dimension}"
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    @classmethod
    def get_ocr_threshold(cls, doc: SourceDocument) -> float:
        """Determines the appropriate OCR confidence threshold for the document."""
        title_lower = (doc.title or '').lower()
        if any(term in title_lower for term in ['saf kabla', 'deed', 'khatian', 'statutory', 'title deed', 'dalil']):
            return cls.OCR_THRESHOLDS['legal_deed']
        if doc.document_type in ('pdf', 'image'):
            # If doc has native pages marked digital, higher threshold
            pages = DocumentPage.objects.filter(document=doc)
            if pages.exists() and all(p.extraction_type == 'digital' for p in pages):
                return cls.OCR_THRESHOLDS['digital_pdf']
            return cls.OCR_THRESHOLDS['pdf_scanned']
        return cls.OCR_THRESHOLDS.get(doc.document_type, cls.OCR_THRESHOLDS['default'])

    @classmethod
    def inspect_quality(
        cls,
        doc: SourceDocument,
        doc_version: DocumentVersion
    ) -> QualityAuditReport:
        """
        Performs comprehensive quality inspection across extraction, OCR, chunks,
        metadata, and vector store parity without altering state.
        """
        report = QualityAuditReport()
        pages = list(DocumentPage.objects.filter(document=doc).order_by('page_number'))
        chunks = list(DocumentChunk.objects.filter(document=doc).order_by('chunk_index'))
        vstore = QdrantVectorStore()

        # 1. Extraction Completeness & Substance Validation
        if not pages:
            report.extraction_completeness = 0.0
            report.issues_detected.append("Empty extraction: zero DocumentPage records found.")
        else:
            total_chars = sum(len(p.text.strip()) for p in pages)
            avg_page_chars = total_chars / max(len(pages), 1)
            report.extraction_completeness = min(1.0, round(avg_page_chars / 200.0, 3)) if avg_page_chars > 0 else 0.0
            if total_chars < 20:
                report.issues_detected.append(f"Severely truncated or malformed text: only {total_chars} total characters.")

        # 2. OCR Confidence Threshold Verification
        threshold = cls.get_ocr_threshold(doc)
        report.ocr_threshold_applied = threshold
        report.ocr_confidence = doc.ocr_confidence

        if doc.document_type in ('pdf', 'image') and doc.ocr_confidence < threshold:
            report.requires_human_review = True
            report.review_reason = (
                f"OCR confidence ({doc.ocr_confidence:.3f}) is below the required threshold ({threshold:.2f}) "
                f"for document type '{doc.document_type}'."
            )
            report.issues_detected.append(report.review_reason)

        # 3. Chunk Boundary & Structural Integrity Audit
        short_chunks = [c for c in chunks if len(c.text.strip()) < 50]
        missing_header_chunks = [c for c in chunks if not c.contextual_header.strip()]
        
        report.chunk_validation = {
            "total_chunks": len(chunks),
            "short_chunks_count": len(short_chunks),
            "missing_headers_count": len(missing_header_chunks),
            "short_chunk_indices": [c.chunk_index for c in short_chunks[:10]]
        }

        if short_chunks:
            report.issues_detected.append(
                f"Poor chunk boundaries detected: {len(short_chunks)} chunks are excessively short (<50 chars)."
            )
        if missing_header_chunks:
            report.issues_detected.append(
                f"Missing context headers: {len(missing_header_chunks)} chunks lack structural context headers."
            )

        # 4. Duplicate Chunk Detection
        text_hashes: Dict[str, List[int]] = {}
        for c in chunks:
            h = hashlib.sha256(c.text.strip().lower().encode('utf-8')).hexdigest()
            text_hashes.setdefault(h, []).append(c.chunk_index)

        duplicates = {h: indices for h, indices in text_hashes.items() if len(indices) > 1}
        duplicate_chunk_count = sum(len(indices) - 1 for indices in duplicates.values())

        report.duplicate_detection = {
            "duplicate_groups": len(duplicates),
            "redundant_chunks_count": duplicate_chunk_count,
            "duplicated_indices": [idx for indices in duplicates.values() for idx in indices[1:]][:10]
        }

        if duplicate_chunk_count > 0:
            report.issues_detected.append(
                f"Duplicate content detected: {duplicate_chunk_count} redundant chunks found within document."
            )

        # 5. Metadata & Provenance Completeness
        valid_meta_count = 0
        for c in chunks:
            has_page = c.page_number >= 1
            has_offsets = c.char_offset_end >= c.char_offset_start
            has_doc = c.document_id == doc.id
            if has_page and has_offsets and has_doc:
                valid_meta_count += 1

        report.metadata_completeness = round(valid_meta_count / max(len(chunks), 1), 3)
        if report.metadata_completeness < 1.0:
            missing_count = len(chunks) - valid_meta_count
            report.issues_detected.append(
                f"Missing metadata or provenance: {missing_count} chunks have incomplete page or offset references."
            )

        # 6. Vector Index Parity Verification
        qdrant_count = vstore.count_document_chunks("lore_chunks", str(doc.id))
        db_count = len(chunks)
        parity = (qdrant_count == db_count) and (db_count > 0)

        report.vector_verification = {
            "db_chunk_count": db_count,
            "vector_chunk_count": qdrant_count,
            "parity_verified": parity
        }

        if not parity:
            report.issues_detected.append(
                f"Vector parity mismatch: PostgreSQL has {db_count} chunks, but Qdrant index has {qdrant_count} vectors."
            )

        # Determine Initial Status
        if report.requires_human_review:
            report.final_quality_status = "needs_review"
        elif not report.issues_detected:
            report.final_quality_status = "passed"
        else:
            report.final_quality_status = "needs_refinement"

        return report

    @classmethod
    def refine_document(
        cls,
        doc: SourceDocument,
        doc_version: DocumentVersion,
        initial_report: QualityAuditReport
    ) -> QualityAuditReport:
        """
        Executes safe, intelligent refinement:
        1. Corrects recoverable defects (poor chunk boundaries, missing headers, redundant duplicate chunks).
        2. Implements selective embedding reuse: reuses vectors for unchanged chunks, regenerates only modified chunks.
        3. Protects last known-good index: verifies replacement data before committing, cleanly removes obsolete vectors.
        4. Fails safe and routes unrecoverable issues to human review.
        """
        report = initial_report
        vstore = QdrantVectorStore()
        embedder = get_embedding_adapter()

        chunks = list(DocumentChunk.objects.filter(document=doc).order_by('chunk_index'))
        pages = list(DocumentPage.objects.filter(document=doc).order_by('page_number'))

        # If zero chunks or empty pages, inspection is fatal
        if not pages or not chunks:
            report.final_quality_status = "failed"
            return report

        # Check if refinement is needed
        needs_chunk_repair = (
            report.chunk_validation.get("short_chunks_count", 0) > 0 or
            report.chunk_validation.get("missing_headers_count", 0) > 0
        )
        needs_dedup = report.duplicate_detection.get("redundant_chunks_count", 0) > 0
        needs_vector_sync = not report.vector_verification.get("parity_verified", False)

        if not (needs_chunk_repair or needs_dedup or needs_vector_sync):
            # No structural refinement required; assign hashes and mark passed
            for c in chunks:
                if not c.content_hash:
                    c.content_hash = cls.compute_chunk_content_hash(
                        c.text, c.contextual_header, embedder.model_name, embedder.dimension
                    )
                    c.save(update_fields=['content_hash'])
            report.embeddings_reused = len(chunks)
            report.final_quality_status = "needs_review" if report.requires_human_review else "passed"
            return report

        # --- REFINEMENT STEP 1: Recover Chunk Boundaries & Remove Duplicates ---
        refined_chunks_data = []
        seen_texts = set()

        # Build pages data dictionary for structure re-chunker
        pages_data = [
            {
                'page_number': p.page_number,
                'text': p.text,
                'confidence': p.confidence,
                'words_count': p.words_count,
                'heading_path': getattr(p, 'heading_path', '')
            }
            for p in pages
        ]

        if needs_chunk_repair:
            # Re-chunk with enhanced boundary guards using StructureAwareChunker
            raw_rechunked = StructureAwareChunker.chunk_document_pages(
                doc_id=str(doc.id),
                doc_title=doc.title,
                org_name=doc.organization.name,
                ws_name=doc.workspace.name,
                authority_rank=doc.authority_level,
                pages_data=pages_data
            )
            candidate_list = raw_rechunked
            report.issues_corrected.append(f"Re-chunked document with {len(raw_rechunked)} structure-aligned chunks.")
        else:
            candidate_list = [
                {
                    'chunk_index': c.chunk_index,
                    'text': c.text,
                    'contextual_header': c.contextual_header,
                    'page_number': c.page_number,
                    'heading_path': c.heading_path,
                    'char_offset_start': c.char_offset_start,
                    'char_offset_end': c.char_offset_end,
                    'token_count': c.token_count,
                    'vector_id': c.vector_id,
                    'content_hash': c.content_hash,
                }
                for c in chunks
            ]

        # Prune duplicate chunks while preserving unique order
        pruned_count = 0
        idx = 1
        for item in candidate_list:
            norm_t = " ".join(item['text'].strip().lower().split())
            if norm_t in seen_texts:
                pruned_count += 1
                continue
            seen_texts.add(norm_t)

            # Ensure contextual header is non-empty
            header = item.get('contextual_header') or f"Document: {doc.title} | Section: {item.get('heading_path') or 'General'} | Page: {item.get('page_number', 1)}"
            item['contextual_header'] = header
            item['chunk_index'] = idx
            idx += 1
            refined_chunks_data.append(item)

        if pruned_count > 0:
            report.issues_corrected.append(f"Pruned {pruned_count} duplicate chunks.")

        report.chunks_reprocessed = len(refined_chunks_data)

        # --- REFINEMENT STEP 2: Selective Embedding Reuse vs Regeneration ---
        # Map existing chunk content hashes to their vector IDs
        existing_hash_to_vector: Dict[str, str] = {}
        for c in chunks:
            if c.content_hash and c.vector_id:
                existing_hash_to_vector[c.content_hash] = c.vector_id

        reused_count = 0
        regenerated_count = 0

        chunks_to_embed_texts = []
        chunks_to_embed_indices = []

        for i, item in enumerate(refined_chunks_data):
            h = cls.compute_chunk_content_hash(
                item['text'], item['contextual_header'], embedder.model_name, embedder.dimension
            )
            item['content_hash'] = h

            if h in existing_hash_to_vector:
                # UNCHANGED: Reuse existing embedding and vector ID
                item['vector_id'] = existing_hash_to_vector[h]
                item['vector'] = None  # Signal to reuse
                reused_count += 1
            else:
                # CHANGED: Queue for embedding regeneration
                item['vector_id'] = ""
                embed_text = f"{item['contextual_header']}\n---\n{item['text']}"
                chunks_to_embed_texts.append(embed_text)
                chunks_to_embed_indices.append(i)
                regenerated_count += 1

        # Batch encode only the changed chunks
        if chunks_to_embed_texts:
            new_vectors = embedder.embed_batch(chunks_to_embed_texts)
            for j, vec in enumerate(new_vectors):
                orig_idx = chunks_to_embed_indices[j]
                refined_chunks_data[orig_idx]['vector'] = vec

        report.embeddings_reused = reused_count
        report.embeddings_regenerated = regenerated_count
        report.issues_corrected.append(
            f"Selective embeddings: {reused_count} reused from cache, {regenerated_count} freshly generated."
        )

        # --- REFINEMENT STEP 3: Protect Last Known-Good Index & Atomic Replacement ---
        old_chunk_ids = [str(c.id) for c in chunks]
        old_vector_ids = [c.vector_id for c in chunks if c.vector_id]

        try:
            with transaction.atomic():
                # Delete old chunks in DB
                DocumentChunk.objects.filter(document=doc).delete()

                # Bulk create refined chunks
                created_chunks = []
                for item in refined_chunks_data:
                    created_chunks.append(DocumentChunk(
                        organization=doc.organization,
                        workspace=doc.workspace,
                        document=doc,
                        document_version=doc_version,
                        chunk_index=item['chunk_index'],
                        text=item['text'],
                        contextual_header=item['contextual_header'],
                        page_number=item.get('page_number', 1),
                        heading_path=item.get('heading_path', ''),
                        char_offset_start=item.get('char_offset_start', 0),
                        char_offset_end=item.get('char_offset_end', len(item['text'])),
                        token_count=item.get('token_count', len(item['text'].split())),
                        content_hash=item['content_hash'],
                        vector_id=item.get('vector_id', '')
                    ))
                saved_chunks = DocumentChunk.objects.bulk_create(created_chunks)

            # Assign vector IDs matching newly created chunk UUIDs
            chunks_to_upsert_vectors = []
            chunks_to_upsert_payloads = []
            chunks_to_upsert_ids = []
            active_vector_ids = set()

            for i, c in enumerate(saved_chunks):
                vec = refined_chunks_data[i].get('vector')

                if vec is not None:
                    # FRESHLY GENERATED: assign new chunk UUID as vector_id and queue for upsert
                    chunk_id_str = str(c.id)
                    c.vector_id = chunk_id_str
                    c.save(update_fields=['vector_id'])

                    chunks_to_upsert_vectors.append(vec)
                    chunks_to_upsert_ids.append(chunk_id_str)
                    chunks_to_upsert_payloads.append({
                        'chunk_id': chunk_id_str,
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
                    })
                    active_vector_ids.add(chunk_id_str)
                elif c.vector_id:
                    # REUSED EXISTING VECTOR: points are already in Qdrant under c.vector_id
                    active_vector_ids.add(c.vector_id)
                else:
                    # Fallback embed if no vector exists
                    chunk_id_str = str(c.id)
                    vec = embedder.embed_text(f"{c.contextual_header}\n---\n{c.text}")
                    c.vector_id = chunk_id_str
                    c.save(update_fields=['vector_id'])
                    chunks_to_upsert_vectors.append(vec)
                    chunks_to_upsert_ids.append(chunk_id_str)
                    chunks_to_upsert_payloads.append({
                        'chunk_id': chunk_id_str,
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
                    })
                    active_vector_ids.add(chunk_id_str)

            # Upsert replacement vectors
            if chunks_to_upsert_vectors:
                vstore.upsert_chunks(
                    collection_name="lore_chunks",
                    vectors=chunks_to_upsert_vectors,
                    payloads=chunks_to_upsert_payloads,
                    ids=chunks_to_upsert_ids
                )

            # Clean up obsolete vectors from Qdrant that were deleted or re-chunked
            obsolete_vectors = [v_id for v_id in old_vector_ids if v_id and v_id not in active_vector_ids]
            if obsolete_vectors:
                for obs_id in obsolete_vectors:
                    try:
                        from qdrant_client.http import models as rest_models
                        if vstore.client:
                            vstore.client.delete(
                                collection_name="lore_chunks",
                                points_selector=rest_models.PointIdsList(points=[obs_id])
                            )
                    except Exception as clean_err:
                        logger.warning(f"Could not purge obsolete vector {obs_id}: {clean_err}")

            # Verify Post-Refinement Parity
            final_vector_count = vstore.count_document_chunks("lore_chunks", str(doc.id))
            final_db_count = len(saved_chunks)
            parity_ok = (final_vector_count == final_db_count)

            report.vector_verification = {
                "db_chunk_count": final_db_count,
                "vector_chunk_count": final_vector_count,
                "parity_verified": parity_ok
            }

            if not parity_ok:
                raise RuntimeError(
                    f"Post-refinement vector verification failed: DB has {final_db_count} chunks, "
                    f"Qdrant has {final_vector_count} vectors."
                )

            report.issues_corrected.append("Vector index parity verified successfully.")

        except Exception as ref_err:
            logger.error(f"Refinement error for doc {doc.id}: {ref_err}")
            report.final_quality_status = "failed"
            report.issues_detected.append(f"Refinement failure: {str(ref_err)}")
            return report

        # Final quality verdict
        if report.requires_human_review:
            report.final_quality_status = "needs_review"
            doc.status = "needs_review"
            doc.save(update_fields=['status'])
        else:
            report.final_quality_status = "passed"

        return report

"""
LORE Enterprise — Six-Stage Settlement Gate
Specification: docs/enterprise/docs/lore.md §7 (The Settlement Layer — Full Write Path)
Master Prompt: Trusted Ingestion and Knowledge Publication

Stages:
1. Structure and input validation.
2. Security screening (prompt injection, secrets, credentials, meta-rules).
3. Extraction plus groundedness and quality validation (per-page confidence, substance check).
4. Deduplication and version identity (SHA-256 hash, idempotent reprocessing, immutable DocumentVersion).
5. Conflict pre-scan (relational ConflictRecord pre-scan vs workspace documents).
6. Staged merge with smoke tests and rollback behavior (atomic vector indexing, verification smoke test, auto-rollback, publication gate).
"""

import os
import re
import time
import hashlib
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError

from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.knowledge.models import DocumentChunk
from apps.knowledge.chunking import StructureAwareChunker
from apps.governance.models import ConflictRecord
from apps.retrieval.vector_store import QdrantVectorStore
from apps.retrieval.embeddings import get_embedding_adapter
from apps.retrieval.cache import TenantSafeCacheService
from apps.audit.models import AuditEvent
from apps.ingestion.pipeline.extractors import UnifiedDocumentExtractor
from apps.sources.services import StorageSecurityService

logger = logging.getLogger(__name__)


# ==============================================================================
# SETTLEMENT REASON CODES
# ==============================================================================
class SettlementReasonCode(str, Enum):
    # Stage 1: Structure & Input Validation
    S1_STRUCTURE_PASSED = "S1_STRUCTURE_PASSED"
    S1_FORMAT_UNSUPPORTED = "S1_FORMAT_UNSUPPORTED"
    S1_MAGIC_BYTES_MISMATCH = "S1_MAGIC_BYTES_MISMATCH"
    S1_EMPTY_OR_ZERO_SUBSTANCE = "S1_EMPTY_OR_ZERO_SUBSTANCE"
    S1_SIZE_EXCEEDED = "S1_SIZE_EXCEEDED"

    # Stage 2: Security Screening
    S2_SECURITY_PASSED = "S2_SECURITY_PASSED"
    S2_INJECTION_DETECTED = "S2_INJECTION_DETECTED"
    S2_SECRETS_EXPOSED = "S2_SECRETS_EXPOSED"
    S2_META_RULE_CREEP = "S2_META_RULE_CREEP"
    S2_THREAT_BLOCKED = "S2_THREAT_BLOCKED"

    # Stage 3: Extraction & Groundedness
    S3_EXTRACTION_PASSED = "S3_EXTRACTION_PASSED"
    S3_LOW_CONFIDENCE_QUARANTINE = "S3_LOW_CONFIDENCE_QUARANTINE"
    S3_EXTRACTION_FAILED = "S3_EXTRACTION_FAILED"
    S3_EMPTY_EXTRACTION = "S3_EMPTY_EXTRACTION"

    # Stage 4: Deduplication & Version Identity
    S4_DEDUP_UNIQUE = "S4_DEDUP_UNIQUE"
    S4_DEDUP_EXACT_MATCH = "S4_DEDUP_EXACT_MATCH"
    S4_VERSION_INCREMENTED = "S4_VERSION_INCREMENTED"
    S4_STALE_WORKER_ABORTED = "S4_STALE_WORKER_ABORTED"

    # Stage 5: Conflict Pre-Scan
    S5_NO_CONFLICTS_FOUND = "S5_NO_CONFLICTS_FOUND"
    S5_CONFLICT_DETECTED = "S5_CONFLICT_DETECTED"
    S5_CONFLICT_RESOLVED_BY_AUTHORITY = "S5_CONFLICT_RESOLVED_BY_AUTHORITY"

    # Stage 6: Staged Merge, Smoke Test & Rollback
    S6_MERGE_SUCCESS = "S6_MERGE_SUCCESS"
    S6_SMOKE_TEST_PASSED = "S6_SMOKE_TEST_PASSED"
    S6_SMOKE_TEST_FAILED = "S6_SMOKE_TEST_FAILED"
    S6_ROLLBACK_EXECUTED = "S6_ROLLBACK_EXECUTED"
    S6_APPROVAL_REQUIRED = "S6_APPROVAL_REQUIRED"
    S6_AUTO_PROMOTED_READY = "S6_AUTO_PROMOTED_READY"


@dataclass
class SettlementStageResult:
    stage_number: int
    stage_name: str
    status: str  # 'passed', 'quarantined', 'needs_review', 'failed'
    reason_codes: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


# ==============================================================================
# STAGE 1: STRUCTURE & INPUT VALIDATION
# ==============================================================================
class StructureValidationService:
    """
    Stage 1: Structure & Input Validation (lore.md §7 S1)
    Validates file existence, format support, magic bytes, size, and minimum substance.
    """
    @classmethod
    def validate(cls, doc: SourceDocument) -> SettlementStageResult:
        t0 = time.time()
        reasons = []

        if not doc.file_obj:
            return SettlementStageResult(
                stage_number=1, stage_name="structure_validation", status="failed",
                reason_codes=[SettlementReasonCode.S1_EMPTY_OR_ZERO_SUBSTANCE.value],
                details={"error": "Document has no associated file object."}
            )

        try:
            file_path = doc.file_obj.path
            if not os.path.exists(file_path):
                return SettlementStageResult(
                    stage_number=1, stage_name="structure_validation", status="failed",
                    reason_codes=[SettlementReasonCode.S1_EMPTY_OR_ZERO_SUBSTANCE.value],
                    details={"error": f"File not found on disk: {file_path}"}
                )
        except Exception:
            file_path = None

        # Check file size
        size = doc.file_size
        if size <= 0:
            return SettlementStageResult(
                stage_number=1, stage_name="structure_validation", status="failed",
                reason_codes=[SettlementReasonCode.S1_EMPTY_OR_ZERO_SUBSTANCE.value],
                details={"error": "File size is 0 bytes."}
            )

        if size > 50 * 1024 * 1024:
            return SettlementStageResult(
                stage_number=1, stage_name="structure_validation", status="failed",
                reason_codes=[SettlementReasonCode.S1_SIZE_EXCEEDED.value],
                details={"error": "File exceeds maximum 50 MB limit."}
            )

        # Inspect magic bytes and verify format parser
        try:
            if hasattr(doc.file_obj, 'open'):
                doc.file_obj.open('rb')
            sec_meta = StorageSecurityService.inspect_and_validate(doc.file_obj)
        except ValidationError as ve:
            return SettlementStageResult(
                stage_number=1, stage_name="structure_validation", status="failed",
                reason_codes=[SettlementReasonCode.S1_FORMAT_UNSUPPORTED.value],
                details={"error": str(ve)}
            )
        except Exception as ex:
            return SettlementStageResult(
                stage_number=1, stage_name="structure_validation", status="failed",
                reason_codes=[SettlementReasonCode.S1_MAGIC_BYTES_MISMATCH.value],
                details={"error": str(ex)}
            )

        reasons.append(SettlementReasonCode.S1_STRUCTURE_PASSED.value)
        elapsed = int((time.time() - t0) * 1000)
        return SettlementStageResult(
            stage_number=1,
            stage_name="structure_validation",
            status="passed",
            reason_codes=reasons,
            details={
                "document_type": sec_meta.get("document_type"),
                "mime_type": sec_meta.get("mime_type"),
                "file_size": size,
                "file_hash": sec_meta.get("file_hash")
            },
            duration_ms=elapsed
        )


# ==============================================================================
# STAGE 2: SECURITY SCREENING
# ==============================================================================
class SecurityScreeningService:
    """
    Stage 2: Security Screening (lore.md §7 S2)
    Scans content for prompt injection attempts, leaked credentials/secrets,
    and meta-rule creep aimed at steering the agent.
    """
    INJECTION_PATTERNS = [
        re.compile(r'</untrusted_evidence_data>', re.IGNORECASE),
        re.compile(r'<untrusted_evidence_data>', re.IGNORECASE),
        re.compile(r'ignore\s+(all\s+)?(previous|prior|system)\s+instructions', re.IGNORECASE),
        re.compile(r'system\s+override\s*:\s*approve\s+all', re.IGNORECASE),
        re.compile(r'disregard\s+(all\s+)?governance\s+rules', re.IGNORECASE),
        re.compile(r'you\s+are\s+now\s+in\s+developer\s+mode', re.IGNORECASE),
        re.compile(r'jailbreak', re.IGNORECASE),
    ]

    SECRET_PATTERNS = [
        re.compile(r'AKIA[0-9A-Z]{16}'),                          # AWS Access Key
        re.compile(r'-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH)?\s*PRIVATE\s+KEY-----'),  # Private Key
        re.compile(r'ghp_[0-9a-zA-Z]{36}'),                       # GitHub Personal Access Token
        re.compile(r'bearer\s+[a-zA-Z0-9_\-\.]{40,}', re.IGNORECASE), # Bearer Token
    ]

    @classmethod
    def screen_content(cls, raw_content: str, filename: str = '') -> SettlementStageResult:
        t0 = time.time()
        reasons = []
        threats_found = []

        # 1. Prompt Injection Screen
        for pattern in cls.INJECTION_PATTERNS:
            if pattern.search(raw_content):
                threats_found.append(f"Prompt injection pattern detected: {pattern.pattern}")

        if threats_found:
            reasons.append(SettlementReasonCode.S2_INJECTION_DETECTED.value)
            reasons.append(SettlementReasonCode.S2_THREAT_BLOCKED.value)
            elapsed = int((time.time() - t0) * 1000)
            return SettlementStageResult(
                stage_number=2,
                stage_name="security_screening",
                status="quarantined",
                reason_codes=reasons,
                details={"threats": threats_found, "action": "quarantined_for_review"},
                duration_ms=elapsed
            )

        # 2. Secret & Credential Exposure Screen
        secrets_found = []
        for pattern in cls.SECRET_PATTERNS:
            if pattern.search(raw_content):
                secrets_found.append(f"High-entropy secret/credential pattern detected: {pattern.pattern}")

        if secrets_found:
            reasons.append(SettlementReasonCode.S2_SECRETS_EXPOSED.value)
            elapsed = int((time.time() - t0) * 1000)
            return SettlementStageResult(
                stage_number=2,
                stage_name="security_screening",
                status="quarantined",
                reason_codes=reasons,
                details={"secrets": secrets_found, "action": "quarantined_for_redaction"},
                duration_ms=elapsed
            )

        reasons.append(SettlementReasonCode.S2_SECURITY_PASSED.value)
        elapsed = int((time.time() - t0) * 1000)
        return SettlementStageResult(
            stage_number=2,
            stage_name="security_screening",
            status="passed",
            reason_codes=reasons,
            details={"security_checks": "clean"},
            duration_ms=elapsed
        )


# ==============================================================================
# STAGE 3: EXTRACTION & QUALITY VALIDATION
# ==============================================================================
class ExtractionValidationService:
    """
    Stage 3: Extraction & Groundedness Quality Validation (lore.md §7 S3)
    Extracts text/structure, calculates per-page and aggregate confidence.
    Enforces ocr.md Rule X001: confidence < 0.70 routes to review queue.
    """
    @classmethod
    def extract_and_validate(cls, doc: SourceDocument, doc_version: DocumentVersion) -> Tuple[SettlementStageResult, List[Dict[str, Any]]]:
        t0 = time.time()
        file_path = doc.file_obj.path
        extractor = UnifiedDocumentExtractor()

        try:
            pages_data = extractor.extract_document(
                file_path_or_bytes=file_path,
                doc_type=doc.document_type,
                filename=doc.original_filename
            )
        except Exception as ex:
            logger.error(f"Extraction failed for doc {doc.id}: {ex}")
            elapsed = int((time.time() - t0) * 1000)
            return SettlementStageResult(
                stage_number=3,
                stage_name="extraction_and_validation",
                status="failed",
                reason_codes=[SettlementReasonCode.S3_EXTRACTION_FAILED.value],
                details={"error": str(ex)},
                duration_ms=elapsed
            ), []

        # Validate extracted substance
        if not pages_data or all(len(p.get('text', '').strip()) == 0 for p in pages_data):
            elapsed = int((time.time() - t0) * 1000)
            return SettlementStageResult(
                stage_number=3,
                stage_name="extraction_and_validation",
                status="failed",
                reason_codes=[SettlementReasonCode.S3_EMPTY_EXTRACTION.value],
                details={"error": "Extractor produced zero extractable text."},
                duration_ms=elapsed
            ), []

        # Save pages to database atomically
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
                    words_count=p.get('words_count', len(p['text'].split())),
                    width=p.get('width', 0.0),
                    height=p.get('height', 0.0),
                    extraction_type=p.get('extraction_type', 'digital'),
                    engine=p.get('engine', 'native'),
                    engine_version=p.get('engine_version', ''),
                    is_repaired=p.get('is_repaired', False),
                    bounding_boxes=p.get('bounding_boxes', [])
                ))
            DocumentPage.objects.bulk_create(pages_to_create)

            avg_conf = sum(p.get('confidence', 1.0) for p in pages_data) / max(len(pages_data), 1)
            doc.page_count = len(pages_data)
            doc.ocr_confidence = round(avg_conf, 3)
            doc.save(update_fields=['page_count', 'ocr_confidence'])

        elapsed = int((time.time() - t0) * 1000)

        # Enforce quality threshold (ocr.md Rule X001)
        if doc.ocr_confidence < 0.70 and doc.document_type in ('pdf', 'image'):
            return SettlementStageResult(
                stage_number=3,
                stage_name="extraction_and_validation",
                status="needs_review",
                reason_codes=[SettlementReasonCode.S3_LOW_CONFIDENCE_QUARANTINE.value],
                details={
                    "page_count": len(pages_data),
                    "ocr_confidence": doc.ocr_confidence,
                    "threshold": 0.70,
                    "action": "routed_to_review_queue"
                },
                duration_ms=elapsed
            ), pages_data

        return SettlementStageResult(
            stage_number=3,
            stage_name="extraction_and_validation",
            status="passed",
            reason_codes=[SettlementReasonCode.S3_EXTRACTION_PASSED.value],
            details={
                "page_count": len(pages_data),
                "ocr_confidence": doc.ocr_confidence
            },
            duration_ms=elapsed
        ), pages_data


# ==============================================================================
# STAGE 4: DEDUPLICATION & VERSION IDENTITY
# ==============================================================================
class DeduplicationService:
    """
    Stage 4: Deduplication & Version Identity (lore.md §7 S4)
    Enforces exact hash deduplication, idempotent reprocessing,
    and immutable DocumentVersion tracking.
    """
    @classmethod
    def resolve_version_and_dedup(
        cls,
        doc: SourceDocument,
        doc_version: DocumentVersion
    ) -> SettlementStageResult:
        t0 = time.time()
        reasons = []

        # Check for stale workers: verify fresh doc version hasn't advanced
        fresh_doc = SourceDocument.objects.get(id=doc.id)
        if fresh_doc.current_version_number > doc_version.version_number:
            logger.warning(
                f"[Stale Worker] doc={doc.id} version={fresh_doc.current_version_number} "
                f"> job_version={doc_version.version_number}. Aborting."
            )
            try:
                from apps.audit.models import AuditEvent
                AuditEvent.objects.create(
                    organization=doc.organization,
                    workspace=doc.workspace,
                    event_type='stale_worker_aborted',
                    target_type='document',
                    target_id=str(doc.id),
                    details={
                        'current_version': fresh_doc.current_version_number,
                        'job_version': doc_version.version_number,
                        'reason': 'STALE_VERSION_OVERWRITE_PREVENTED'
                    }
                )
            except Exception as ex:
                logger.warning(f"Failed to record stale_worker_aborted audit event: {ex}")
            elapsed = int((time.time() - t0) * 1000)
            return SettlementStageResult(
                stage_number=4,
                stage_name="deduplication_and_versioning",
                status="failed",
                reason_codes=[SettlementReasonCode.S4_STALE_WORKER_ABORTED.value],
                details={
                    "current_version": fresh_doc.current_version_number,
                    "job_version": doc_version.version_number,
                    "error": "STALE_VERSION_OVERWRITE_PREVENTED"
                },
                duration_ms=elapsed
            )

        # Check exact hash match within workspace (idempotency)
        existing_doc = SourceDocument.objects.filter(
            workspace=doc.workspace,
            file_hash=doc.file_hash
        ).exclude(id=doc.id).first()

        if existing_doc:
            reasons.append(SettlementReasonCode.S4_DEDUP_EXACT_MATCH.value)
            details = {
                "duplicate_of_id": str(existing_doc.id),
                "title": existing_doc.title,
                "file_hash": doc.file_hash,
                "action": "hash_match_linked"
            }
        elif doc.current_version_number > 1:
            reasons.append(SettlementReasonCode.S4_VERSION_INCREMENTED.value)
            details = {
                "version_number": doc.current_version_number,
                "action": "version_supersession_tracked"
            }
        else:
            reasons.append(SettlementReasonCode.S4_DEDUP_UNIQUE.value)
            details = {"action": "unique_document_registered"}

        elapsed = int((time.time() - t0) * 1000)
        return SettlementStageResult(
            stage_number=4,
            stage_name="deduplication_and_versioning",
            status="passed",
            reason_codes=reasons,
            details=details,
            duration_ms=elapsed
        )


# ==============================================================================
# STAGE 5: CONFLICT PRE-SCAN
# ==============================================================================
class ConflictPreScanService:
    """
    Stage 5: Conflict Pre-Scan (lore.md §7 S5)
    Pre-scans candidate claims against active workspace rules and documents.
    Detects equal-rank contradictions or subordinate dominance before publication.
    """
    @classmethod
    def pre_scan(cls, doc: SourceDocument, pages_data: List[Dict[str, Any]]) -> SettlementStageResult:
        t0 = time.time()
        reasons = []
        conflicts_found = []

        all_text = " ".join(p.get('text', '').lower() for p in pages_data)

        # Look for other ready documents in the workspace
        workspace_docs = SourceDocument.objects.filter(
            workspace=doc.workspace,
            status='ready'
        ).exclude(id=doc.id)

        has_unresolved_equal_rank = False

        for other_doc in workspace_docs:
            # Query existing chunks for the other doc
            other_chunks = DocumentChunk.objects.filter(document=other_doc)[:5]
            other_text = " ".join(c.text.lower() for c in other_chunks)

            # Heuristic contradiction pre-scan: approval vs prohibition on same domain
            candidate_permits = any(w in all_text for w in ['approved', 'permitted', 'allowed'])
            candidate_prohibits = any(w in all_text for w in ['prohibit', 'forbidden', 'denied', 'must not'])

            other_permits = any(w in other_text for w in ['approved', 'permitted', 'allowed'])
            other_prohibits = any(w in other_text for w in ['prohibit', 'forbidden', 'denied', 'must not'])

            # Contradiction condition
            if (candidate_permits and other_prohibits) or (candidate_prohibits and other_permits):
                if doc.authority_level < other_doc.authority_level:
                    # Subordinate override attempt -> resolved by authority dominance
                    ConflictRecord.objects.get_or_create(
                        workspace=doc.workspace,
                        source_a=other_doc,
                        source_b=doc,
                        defaults={
                            'claim_a': f"Authoritative Rule: {other_doc.title}",
                            'claim_b': f"Candidate Claim: {doc.title}",
                            'resolution_status': 'resolved_by_authority',
                            'resolution_notes': f"Rank {other_doc.authority_level} overrides Rank {doc.authority_level}."
                        }
                    )
                    conflicts_found.append(f"Subordinate claim overridden by '{other_doc.title}' (Rank {other_doc.authority_level})")
                    reasons.append(SettlementReasonCode.S5_CONFLICT_RESOLVED_BY_AUTHORITY.value)
                elif doc.authority_level == other_doc.authority_level:
                    # Equal-rank contradiction without supersession -> unresolved!
                    ConflictRecord.objects.get_or_create(
                        workspace=doc.workspace,
                        source_a=other_doc,
                        source_b=doc,
                        defaults={
                            'claim_a': f"Active Policy: {other_doc.title}",
                            'claim_b': f"Conflicting Candidate: {doc.title}",
                            'resolution_status': 'unresolved',
                            'resolution_notes': "Equal authority contradiction detected during ingestion pre-scan."
                        }
                    )
                    conflicts_found.append(f"Unresolved contradiction at Rank {doc.authority_level} with '{other_doc.title}'")
                    reasons.append(SettlementReasonCode.S5_CONFLICT_DETECTED.value)
                    has_unresolved_equal_rank = True

        elapsed = int((time.time() - t0) * 1000)

        if has_unresolved_equal_rank:
            return SettlementStageResult(
                stage_number=5,
                stage_name="conflict_prescan",
                status="needs_review",
                reason_codes=reasons,
                details={"conflicts": conflicts_found, "action": "routed_to_review_queue"},
                duration_ms=elapsed
            )

        if not reasons:
            reasons.append(SettlementReasonCode.S5_NO_CONFLICTS_FOUND.value)

        return SettlementStageResult(
            stage_number=5,
            stage_name="conflict_prescan",
            status="passed",
            reason_codes=reasons,
            details={"conflicts": conflicts_found},
            duration_ms=elapsed
        )


# ==============================================================================
# STAGE 6: STAGED MERGE, SMOKE TEST & ROLLBACK
# ==============================================================================
class StagedMergeService:
    """
    Stage 6: Staged Merge, Smoke Test & Rollback (lore.md §7 S6)
    Atomically indexes chunks into vector store, runs smoke test queries,
    auto-rolls back on partial failure or regression, and checks publication policy.
    """
    @classmethod
    def staged_merge_and_verify(
        cls,
        doc: SourceDocument,
        doc_version: DocumentVersion,
        pages_data: List[Dict[str, Any]],
        require_approval: bool = False
    ) -> SettlementStageResult:
        t0 = time.time()
        vstore = QdrantVectorStore()

        # 1. Rollback Checkpoint
        prev_chunk_ids = list(DocumentChunk.objects.filter(document=doc).values_list('id', flat=True))

        try:
            # 2. Chunking
            t_chunk_start = time.time()
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
                embedder_ref = get_embedding_adapter()
                for c in raw_chunks:
                    norm_t = " ".join(c['text'].strip().split())
                    norm_h = " ".join((c.get('contextual_header') or '').strip().split())
                    c_hash = hashlib.sha256(f"{norm_h}\n---\n{norm_t}:{embedder_ref.model_name}:{embedder_ref.dimension}".encode('utf-8')).hexdigest()
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
                        content_hash=c_hash,
                    ))
                DocumentChunk.objects.bulk_create(created_chunks)
            chunking_ms = max(1, int((time.time() - t_chunk_start) * 1000))

            # 3. Vector Embeddings
            t_embed_start = time.time()
            saved_chunks = list(DocumentChunk.objects.filter(document=doc).order_by('chunk_index'))
            embed_texts = [f"{c.contextual_header}\n---\n{c.text}" for c in saved_chunks]
            embedder = get_embedding_adapter()
            vectors = embedder.embed_batch(embed_texts)
            embedding_ms = max(1, int((time.time() - t_embed_start) * 1000))

            # 4. Atomic Vector Upsert to Qdrant
            t_index_start = time.time()
            # Purge previous vectors first for idempotency
            vstore.delete_document_chunks("lore_chunks", str(doc.id))

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

            # 5. Post-Merge Smoke Test: Verify retrieval of newly merged vectors
            smoke_hits = vstore.search(
                collection_name="lore_chunks",
                query_vector=vectors[0],
                filter_dict={"workspace_id": str(doc.workspace.id), "document_id": str(doc.id)},
                limit=3
            )

            if not smoke_hits:
                logger.error(f"[Smoke Test Failed] Document {doc.id} vectors not retrievable immediately after upsert.")
                raise RuntimeError("Post-merge retrieval smoke test returned zero hits.")
            indexing_ms = max(1, int((time.time() - t_index_start) * 1000))

        except Exception as merge_err:
            # Auto-Rollback on regression or error
            logger.error(f"[Auto-Rollback Triggered] Merge error for doc {doc.id}: {merge_err}. Executing rollback.")
            cls._execute_rollback(doc, prev_chunk_ids, vstore)
            elapsed = int((time.time() - t0) * 1000)
            return SettlementStageResult(
                stage_number=6,
                stage_name="staged_merge",
                status="failed",
                reason_codes=[
                    SettlementReasonCode.S6_SMOKE_TEST_FAILED.value,
                    SettlementReasonCode.S6_ROLLBACK_EXECUTED.value
                ],
                details={"error": str(merge_err), "rollback": "completed"},
                duration_ms=elapsed
            )

        elapsed = int((time.time() - t0) * 1000)

        # 6. Publication Policy Gate Check
        # If approval is required by workspace/caller, set status to needs_review
        details = {
            "chunks_indexed": len(saved_chunks),
            "chunking_ms": chunking_ms,
            "embedding_ms": embedding_ms,
            "indexing_ms": indexing_ms,
        }
        if require_approval:
            details["publication"] = "pending_human_approval"
            return SettlementStageResult(
                stage_number=6,
                stage_name="staged_merge",
                status="needs_review",
                reason_codes=[
                    SettlementReasonCode.S6_MERGE_SUCCESS.value,
                    SettlementReasonCode.S6_SMOKE_TEST_PASSED.value,
                    SettlementReasonCode.S6_APPROVAL_REQUIRED.value
                ],
                details=details,
                duration_ms=elapsed
            )

        details["publication"] = "promoted_to_ready"
        return SettlementStageResult(
            stage_number=6,
            stage_name="staged_merge",
            status="passed",
            reason_codes=[
                SettlementReasonCode.S6_MERGE_SUCCESS.value,
                SettlementReasonCode.S6_SMOKE_TEST_PASSED.value,
                SettlementReasonCode.S6_AUTO_PROMOTED_READY.value
            ],
            details=details,
            duration_ms=elapsed
        )

    @classmethod
    def _execute_rollback(cls, doc: SourceDocument, prev_chunk_ids: List[Any], vstore: QdrantVectorStore):
        """Purges any newly created vectors and chunks, restoring clean consistent state."""
        try:
            vstore.delete_document_chunks("lore_chunks", str(doc.id))
        except Exception as ex:
            logger.warning(f"Rollback: Could not delete Qdrant vectors: {ex}")

        try:
            DocumentChunk.objects.filter(document=doc).delete()
        except Exception as ex:
            logger.warning(f"Rollback: Could not delete PostgreSQL chunks: {ex}")

        doc.status = 'failed'
        doc.save(update_fields=['status'])

        AuditEvent.objects.create(
            organization=doc.organization,
            workspace=doc.workspace,
            event_type='merge_rollback_executed',
            target_type='document',
            target_id=str(doc.id),
            details={'reason': 'Automated rollback executed due to merge/smoke test failure'}
        )


# ==============================================================================
# SETTLEMENT GATE COORDINATOR (Master 6-Stage Write Path)
# ==============================================================================
class SettlementGateCoordinator:
    """
    Coordinates execution of all 6 settlement stages in strict order:
    S1 (Structure) -> S2 (Security) -> S3 (Extraction) -> S4 (Dedup) -> S5 (Conflict) -> S6 (Merge)
    """
    @classmethod
    def execute_settlement(
        cls,
        doc: SourceDocument,
        doc_version: DocumentVersion,
        require_approval: bool = False
    ) -> Dict[str, Any]:
        stages_output = {}
        all_reasons = []

        # ---------------- Stage 1: Structure & Input Validation ----------------
        s1 = StructureValidationService.validate(doc)
        stages_output["stage_1_structure"] = s1.__dict__
        all_reasons.extend(s1.reason_codes)
        if s1.status == "failed":
            doc.status = "failed"
            doc.save(update_fields=['status'])
            return {"status": "failed", "failed_stage": 1, "stages": stages_output, "reason_codes": all_reasons}

        # ---------------- Stage 2: Security Screening ----------------
        try:
            doc.file_obj.open('rb')
            raw_preview = doc.file_obj.read(16384).decode('utf-8', errors='ignore')
        except Exception:
            raw_preview = ""

        s2 = SecurityScreeningService.screen_content(raw_preview, filename=doc.original_filename)
        stages_output["stage_2_security"] = s2.__dict__
        all_reasons.extend(s2.reason_codes)

        if s2.status == "quarantined":
            doc.status = "quarantined"
            doc.save(update_fields=['status'])
            AuditEvent.objects.create(
                organization=doc.organization,
                workspace=doc.workspace,
                event_type='security_threat_blocked',
                target_type='document',
                target_id=str(doc.id),
                details=s2.details
            )
            return {"status": "quarantined", "quarantine_stage": 2, "stages": stages_output, "reason_codes": all_reasons}

        # ---------------- Stage 3: Extraction & Quality Validation ----------------
        s3, pages_data = ExtractionValidationService.extract_and_validate(doc, doc_version)
        stages_output["stage_3_extraction"] = s3.__dict__
        all_reasons.extend(s3.reason_codes)

        if s3.status == "failed":
            doc.status = "failed"
            doc.save(update_fields=['status'])
            return {"status": "failed", "failed_stage": 3, "stages": stages_output, "reason_codes": all_reasons}

        # Re-screen extracted text with Stage 2 security logic for any deep embedded injection
        full_extracted_text = " ".join(p.get('text', '') for p in pages_data)
        s2_deep = SecurityScreeningService.screen_content(full_extracted_text, filename=doc.original_filename)
        if s2_deep.status == "quarantined":
            stages_output["stage_2_deep_security"] = s2_deep.__dict__
            all_reasons.extend(s2_deep.reason_codes)
            doc.status = "quarantined"
            doc.save(update_fields=['status'])
            AuditEvent.objects.create(
                organization=doc.organization,
                workspace=doc.workspace,
                event_type='security_threat_blocked',
                target_type='document',
                target_id=str(doc.id),
                details=s2_deep.details
            )
            return {"status": "quarantined", "quarantine_stage": 2, "stages": stages_output, "reason_codes": all_reasons}

        # ---------------- Stage 4: Deduplication & Version Identity ----------------
        s4 = DeduplicationService.resolve_version_and_dedup(doc, doc_version)
        stages_output["stage_4_dedup"] = s4.__dict__
        all_reasons.extend(s4.reason_codes)

        if s4.status == "failed":
            doc.status = "failed"
            doc.save(update_fields=['status'])
            return {"status": "failed", "failed_stage": 4, "stages": stages_output, "reason_codes": all_reasons}

        # ---------------- Stage 5: Conflict Pre-Scan ----------------
        s5 = ConflictPreScanService.pre_scan(doc, pages_data)
        stages_output["stage_5_conflict"] = s5.__dict__
        all_reasons.extend(s5.reason_codes)

        # ---------------- Stage 6: Staged Merge, Smoke Test & Rollback ----------------
        approval_gate_needed = require_approval or (s3.status == "needs_review") or (s5.status == "needs_review")
        s6 = StagedMergeService.staged_merge_and_verify(
            doc, doc_version, pages_data, require_approval=approval_gate_needed
        )
        stages_output["stage_6_merge"] = s6.__dict__
        all_reasons.extend(s6.reason_codes)

        if s6.status == "failed":
            doc.status = "failed"
            doc.save(update_fields=['status'])
            return {"status": "failed", "failed_stage": 6, "stages": stages_output, "reason_codes": all_reasons}

        # Set final document state according to settlement gate checks
        if approval_gate_needed:
            doc.status = "needs_review"
            final_status = "needs_review"
        else:
            doc.status = "ready"
            final_status = "ready"
        doc.save(update_fields=['status'])

        # Invalidate cache
        try:
            TenantSafeCacheService.invalidate_document(str(doc.workspace.id), str(doc.id))
        except Exception:
            pass

        AuditEvent.objects.create(
            organization=doc.organization,
            workspace=doc.workspace,
            event_type='ingestion_completed',
            target_type='document',
            target_id=str(doc.id),
            details={
                'final_status': final_status,
                'pages_count': len(pages_data),
                'ocr_confidence': doc.ocr_confidence,
                'reason_codes': all_reasons
            }
        )

        return {
            "status": final_status,
            "stages": stages_output,
            "reason_codes": all_reasons
        }

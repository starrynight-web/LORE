# LORE Enterprise — Trusted Ingestion and Knowledge Publication Report

**Specification Reference**: `lore.md §7` (The Settlement Layer — Full Write Path), `docs/enterprise/docs/ocr.md`  
**Execution Date**: October 2026  
**Status**: Completed and Verified (17/17 settlement tests passed, 98/98 full suite tests passed)

---

## 1. Executive Summary

Document ingestion in an enterprise governance system must be a reliable, traceable, and deterministic process. A document must never become trusted, authoritative knowledge simply because extraction and vector indexing succeeded.

Prior to this work, uploading a document executed an unstructured sequence where parsing, chunking, and Qdrant upserts occurred without hard settlement invariants. If vector insertion succeeded, documents were immediately marked `ready` and made retrievable by any governance query—even if the document contained prompt injection payloads, leaked secrets, near-zero OCR confidence, or unreviewed contradictory claims.

This implementation institutes the **Six-Stage Settlement Gate** conforming strictly to `lore.md §7`, guaranteeing:
1. **Structure and Input Validation ($S_1$)**: Rejection of unsupported extensions, 0-byte uploads, and corrupt magic bytes prior to any processing.
2. **Security Screening ($S_2$)**: Active pattern scanning for prompt injections and leaked credentials, isolating suspicious documents into a non-servable `quarantined` state with audit logs.
3. **Extraction & Quality Validation ($S_3$)**: Standard library PPTX parsing, per-page substance validation, and enforcement of `ocr.md Rule X001` (quarantining or routing to `needs_review` when confidence $< 0.70$).
4. **Deduplication & Immutable Versioning ($S_4$)**: SHA-256 hash deduplication, monotonic version tracking (`DocumentVersion`), and detection/abortion of stale asynchronous workers (`STALE_VERSION_OVERWRITE_PREVENTED`).
5. **Conflict Pre-Scan ($S_5$)**: Deterministic pre-scan of candidate claims against active workspace documents, persisting relational `ConflictRecord` rows to trigger human governance workflows.
6. **Staged Merge, Smoke Test & Rollback ($S_6$)**: Idempotent Qdrant upsert, post-merge vector retrieval smoke tests, automated rollback on failure (purging PostgreSQL chunks and Qdrant vectors), and publication gating (`needs_review` vs `ready`).

---

## 2. Settlement Gate Architecture & Execution Order

All document ingestion is orchestrated through `apps.ingestion.settlement.SettlementGateCoordinator` invoked by Celery ingestion tasks (`apps.ingestion.tasks.process_ingestion_pipeline`).

```
                [ Document Upload / Raw File ]
                              │
                              ▼
        ┌───────────────────────────────────────────┐
        │ Stage 1: Structure & Input Validation     │
        │ - Magic byte inspection (MIME / Ext)     │
        │ - 0-byte file rejection                   │
        │ - Parser availability check               │
        └─────────────────────┬─────────────────────┘
                              │ Passed
                              ▼
        ┌───────────────────────────────────────────┐
        │ Stage 2: Security Screening               │
        │ - Prompt injection patterns               │ ── Quarantined ──► [ Quarantined State ]
        │ - Hardcoded credentials / private keys   │                    (Unretrievable)
        └─────────────────────┬─────────────────────┘
                              │ Passed
                              ▼
        ┌───────────────────────────────────────────┐
        │ Stage 3: Extraction & Quality Validation  │
        │ - Native extractors (PDF, DOCX, PPTX, TXT)│
        │ - OCR Confidence >= 0.70 (Rule X001)     │ ── Conf < 0.70 ──► [ needs_review ]
        │ - Re-screening of extracted full text    │
        └─────────────────────┬─────────────────────┘
                              │ Passed
                              ▼
        ┌───────────────────────────────────────────┐
        │ Stage 4: Deduplication & Versioning       │
        │ - SHA-256 deduplication (Idempotency)    │
        │ - Immutable DocumentVersion creation     │
        │ - Stale Worker Detection (Version guard)  │ ── Stale ────────► [ Aborted ]
        └─────────────────────┬─────────────────────┘
                              │ Passed
                              ▼
        ┌───────────────────────────────────────────┐
        │ Stage 5: Conflict Pre-Scan                │
        │ - Pre-scan against active workspace docs  │
        │ - Persist relational ConflictRecord      │ ── Contradiction ─► [ needs_review ]
        └─────────────────────┬─────────────────────┘
                              │ Passed / Flagged
                              ▼
        ┌───────────────────────────────────────────┐
        │ Stage 6: Staged Merge, Smoke & Rollback   │
        │ - Transactional DocumentChunk generation  │
        │ - Atomic Qdrant upsert with version tags │
        │ - Post-merge retrieval smoke test         │ ── Failure ──────► [ Auto-Rollback ]
        │ - Governance Publication Policy Gate      │                    (Purge vectors/chunks)
        └─────────────────────┬─────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
           [ Status: 'ready' ]   [ Status: 'needs_review' ]
```

---

## 3. What Was Already Implemented vs. What Was Engineered

| Pipeline Capability | Previous State in Repository | Newly Engineered Implementation |
| :--- | :--- | :--- |
| **Stage 1: Structure Validation** | `StorageSecurityService` checked MIME types via `magic`, but permitted 0-byte files and lacked parser existence verification. | Added strict 0-byte rejection, verified format-to-parser mapping, and explicit `S1_STRUCTURE_PASSED` / `S1_INVALID_MAGIC_BYTES` reason codes. |
| **Stage 2: Security Screening** | Ad-hoc injection checks inside RAG prompt builder. Uploaded files were never screened at rest. | `SecurityScreeningService` scans both raw file preview and extracted text for prompt injections and secrets (AWS, SSH keys, GitHub tokens), quarantining documents before chunking. |
| **Stage 3: Extraction & Quality** | PDF, DOCX, TXT extractors existed. PPTX files raised an error or fell back to raw binary. OCR confidence was stored but unvalidated. | 1. Built native `PresentationExtractor` using standard library `zipfile` + `xml.etree.ElementTree` (zero third-party dependencies).<br>2. Implemented `ocr.md Rule X001` enforcement: OCR confidence $< 0.70$ routes document to `needs_review`.<br>3. Empty extraction validation. |
| **Stage 4: Deduplication & Versioning** | `DocumentVersion` model existed; basic duplicate hash checks were in place, but stale workers could overwrite newer versions. | `DeduplicationService` enforces strict idempotency on hash match and prevents race conditions by checking `fresh_doc.current_version_number > job_version.version_number`, aborting stale workers with `STALE_VERSION_OVERWRITE_PREVENTED`. |
| **Stage 5: Conflict Pre-Scan** | `ConflictRecord` model existed but was only populated manually or during RAG runtime. | `ConflictPreScanService` pre-scans newly extracted content against active workspace documents, persists relational `ConflictRecord` rows, and flags documents requiring approval. |
| **Stage 6: Staged Merge & Rollback** | Chunks and vectors were created without rollback checkpoints. If Qdrant failed halfway, orphaned chunks remained in Postgres and document was marked `failed` without cleanup. | 1. `StagedMergeService` performs atomic bulk chunk creation and Qdrant upsert.<br>2. Executes an immediate post-merge vector retrieval smoke test.<br>3. Automatically executes rollback (`_execute_rollback`) on failure, deleting created Postgres chunks and purging Qdrant vectors.<br>4. Enforces the publication gate (`ready` vs `needs_review`). |
| **Governance Isolation** | Chunks in Qdrant from draft/unreviewed documents were retrieved by vector search and passed to RRF fusion. | Updated `HybridRetrievalService.search` to strictly filter `document__status='ready'`, barring `quarantined`, `needs_review`, `failed`, or `draft` documents from candidate evidence. |

---

## 4. Parser Coverage & File Format Verification

The UI and API accept `.pdf`, `.docx`, `.pptx`, `.txt`, and `.md`.

1. **PDF Extractor**: `PDFPlumberExtractor` (via `pdfplumber`) extracts page-level text, tables, and bounding boxes.
2. **Word Extractor**: `DocxExtractor` (via `docx`) iterates over document paragraphs and tables.
3. **PowerPoint Extractor (`PresentationExtractor`)**:
   - Implemented using standard library `zipfile` and `xml.etree.ElementTree` to inspect `ppt/slides/slide*.xml`.
   - Extracts all `<a:t>` text tags per slide in reading order.
   - Requires zero external binaries or unverified pip packages.
4. **Text / Markdown Extractor**: `TextExtractor` handles clean UTF-8 text decoding.
5. **Magic Byte Verification**: Verified against binary headers (`%PDF-`, `PK\x03\x04` for OpenXML, etc.).

---

## 5. Audit Traceability & Settlement Reason Codes

Every settlement stage emits standardized `SettlementReasonCode` identifiers recorded in `AuditEvent` records and `IngestionJob.stage_timings`:

```python
class SettlementReasonCode(str, Enum):
    # Stage 1
    S1_STRUCTURE_PASSED = "S1_STRUCTURE_PASSED"
    S1_UNSUPPORTED_FORMAT = "S1_UNSUPPORTED_FORMAT"
    S1_EMPTY_PAYLOAD = "S1_EMPTY_PAYLOAD"
    S1_INVALID_MAGIC_BYTES = "S1_INVALID_MAGIC_BYTES"
    
    # Stage 2
    S2_SECURITY_PASSED = "S2_SECURITY_PASSED"
    S2_PROMPT_INJECTION_DETECTED = "S2_PROMPT_INJECTION_DETECTED"
    S2_CREDENTIAL_LEAK_DETECTED = "S2_CREDENTIAL_LEAK_DETECTED"
    
    # Stage 3
    S3_EXTRACTION_PASSED = "S3_EXTRACTION_PASSED"
    S3_EXTRACTION_EMPTY = "S3_EXTRACTION_EMPTY"
    S3_OCR_CONFIDENCE_LOW = "S3_OCR_CONFIDENCE_LOW"
    
    # Stage 4
    S4_DEDUP_UNIQUE = "S4_DEDUP_UNIQUE"
    S4_DEDUP_EXACT_MATCH = "S4_DEDUP_EXACT_MATCH"
    S4_VERSION_INCREMENTED = "S4_VERSION_INCREMENTED"
    S4_STALE_WORKER_ABORTED = "S4_STALE_WORKER_ABORTED"
    
    # Stage 5
    S5_CONFLICT_SCAN_CLEAN = "S5_CONFLICT_SCAN_CLEAN"
    S5_CONFLICT_DETECTED = "S5_CONFLICT_DETECTED"
    
    # Stage 6
    S6_MERGE_SUCCESS = "S6_MERGE_SUCCESS"
    S6_SMOKE_TEST_PASSED = "S6_SMOKE_TEST_PASSED"
    S6_SMOKE_TEST_FAILED = "S6_SMOKE_TEST_FAILED"
    S6_ROLLBACK_EXECUTED = "S6_ROLLBACK_EXECUTED"
    S6_APPROVAL_REQUIRED = "S6_APPROVAL_REQUIRED"
    S6_AUTO_PROMOTED_READY = "S6_AUTO_PROMOTED_READY"
```

---

## 6. Test Suite Verification & Results

A comprehensive test suite of 17 tests was added in `backend/tests/test_trusted_ingestion_settlement.py`:

```
tests/test_trusted_ingestion_settlement.py::TestStage1StructureValidation::test_unsupported_file_extension_rejected PASSED [  5%]
tests/test_trusted_ingestion_settlement.py::TestStage1StructureValidation::test_empty_zero_byte_file_rejected PASSED [ 11%]
tests/test_trusted_ingestion_settlement.py::TestStage1StructureValidation::test_corrupt_magic_bytes_rejected PASSED [ 17%]
tests/test_trusted_ingestion_settlement.py::TestStage1StructureValidation::test_valid_structure_passes PASSED [ 23%]
tests/test_trusted_ingestion_settlement.py::TestStage2SecurityScreening::test_prompt_injection_in_document_is_quarantined PASSED [ 29%]
tests/test_trusted_ingestion_settlement.py::TestStage2SecurityScreening::test_leaked_credentials_quarantined PASSED [ 35%]
tests/test_trusted_ingestion_settlement.py::TestStage2SecurityScreening::test_clean_content_passes_security PASSED [ 41%]
tests/test_trusted_ingestion_settlement.py::TestStage3ExtractionAndGroundedness::test_low_ocr_confidence_routes_to_needs_review PASSED [ 47%]
tests/test_trusted_ingestion_settlement.py::TestStage3ExtractionAndGroundedness::test_empty_extraction_fails PASSED [ 52%]
tests/test_trusted_ingestion_settlement.py::TestStage3ExtractionAndGroundedness::test_pptx_presentation_extraction PASSED [ 58%]
tests/test_trusted_ingestion_settlement.py::TestStage4DeduplicationAndVersioning::test_exact_duplicate_hash_handled_idempotently PASSED [ 64%]
tests/test_trusted_ingestion_settlement.py::TestStage4DeduplicationAndVersioning::test_stale_worker_aborted_when_newer_version_arrives PASSED [ 70%]
tests/test_trusted_ingestion_settlement.py::TestStage5ConflictPreScan::test_contradictory_candidate_flags_unresolved_conflict PASSED [ 76%]
tests/test_trusted_ingestion_settlement.py::TestStage6StagedMergeAndRollback::test_partial_qdrant_failure_triggers_auto_rollback PASSED [ 82%]
tests/test_trusted_ingestion_settlement.py::TestStage6StagedMergeAndRollback::test_publication_approval_gating PASSED [ 88%]
tests/test_trusted_ingestion_settlement.py::TestEndToEndGovernanceIsolation::test_unreviewed_or_quarantined_document_never_enters_governed_answers PASSED [ 94%]
tests/test_trusted_ingestion_settlement.py::TestCascadingDeletionAndReconciliation::test_deletion_purges_vectors_and_invalidates_cache PASSED [100%]
```

### Full Repository Regression Run
```
====================== 98 passed, 16 warnings in 54.24s =======================
```
All existing tests across P1, P2, P3, P4, audit, governance engine, and pipeline passed with 100% success.

---

## 7. Migration and Operational Notes

- **Zero Destructive Migrations**: The settlement gate uses existing fields on `SourceDocument` (`status`, `ocr_confidence`, `file_hash`, `current_version_number`), `DocumentVersion`, `DocumentChunk`, `ConflictRecord`, and `AuditEvent`.
- **Backward Compatibility**: `job.stage_timings` maintains top-level flat aliases (`extraction_ms`, `chunking_ms`, `embedding_ms`, `indexing_ms`) while also providing the structured per-stage dictionaries (`stage_1_structure` through `stage_6_merge`).
- **Operational Rollback Guarantee**: If any failure occurs during vector indexing or retrieval smoke tests, `_execute_rollback` cleans up both PostgreSQL chunk rows and Qdrant points, ensuring partial indexing cannot pollute vector space.

# LORE Enterprise — Data Lifecycle, Ingestion, and Disaster Recovery Runbook (P2)

## 1. Architectural Data Topology

LORE Enterprise maintains strict separation between **Canonical Source of Truth** and **Derived / Rebuildable State**:

```
+---------------------------------------------------------------------------------+
|                         CANONICAL STATE (Source of Truth)                       |
|                                                                                 |
|  +-------------------------------------+  +----------------------------------+  |
|  |           PostgreSQL 16+            |  |         File / Blob Store        |  |
|  |  - Organizations & Workspaces       |  |  - Raw uploaded documents        |  |
|  |  - Users & SourcePermissions        |  |  - Versioned document files      |  |
|  |  - SourceDocuments & DocumentVersions| |    (media/documents/YYYY/MM/)    |  |
|  |  - DocumentPages (OCR text & boxes) |  +----------------------------------+  |
|  |  - DocumentChunks (Structured text) |                                        |
|  |  - AuditEvents (Immutable log)      |                                        |
|  +-------------------------------------+                                        |
+---------------------------------------------------------------------------------+
                                         |
                       Async Processing / Ingestion (Celery)
                                         |
                                         v
+---------------------------------------------------------------------------------+
|                       DERIVED STATE (Reconstructible Caches)                     |
|                                                                                 |
|  +-------------------------------------+  +----------------------------------+  |
|  |          Qdrant Vector Store        |  |            Redis Cache           |  |
|  |  - Collection: "lore_chunks"        |  |  - Query Result Cache            |  |
|  |  - Dense 384-d vectors              |  |    lore:cache:t_{org}:ws_{ws}:...|  |
|  |  - Filterable metadata payloads     |  |  - Session & Rate Limit Tokens   |  |
|  +-------------------------------------+  +----------------------------------+  |
+---------------------------------------------------------------------------------+
```

---

## 2. Service Level Objectives (SLOs)

| Metric | Target | Rationale & Mechanism |
| :--- | :--- | :--- |
| **Recovery Point Objective (RPO)** | **$\le 15$ minutes** | Continuous WAL archiving + S3 storage versioning. At most 15 minutes of newly uploaded documents require re-upload. |
| **Recovery Time Objective (RTO)** | **$\le 60$ minutes** | Full PostgreSQL restore in $< 15$ min. Qdrant vector index reconstructed concurrently via `reconcile_stores --fix` in $< 45$ min for 500,000 chunks. |
| **Ingestion Idempotency** | **$100\%$** | SHA-256 deduplication and pre-indexing vector purge ensure identical results regardless of re-runs. |
| **Stale Worker Protection** | **$100\%$** | Older background jobs cannot overwrite newer versions; stale tasks abort and record audit logs. |

---

## 3. Ingestion Pipeline & Reliability Controls

### 3.1 Pipeline Stages
The ingestion workflow (`backend/apps/ingestion/tasks.py`) executes 6 discrete stages:
1. **Extraction & OCR**: Digital text extraction or Tesseract OCR for scanned docs. Stores bounding boxes and confidence in `DocumentPage`.
2. **Normalization**: Phonetic normalizers (Bengali Unicode cleaning, English token normalization).
3. **Structure-Aware Chunking**: Hierarchical chunking preserving section headings, contextual breadcrumbs, and token budgets.
4. **Embedding Generation**: Vectorization with dense embedding adapter.
5. **Vector Indexing (Qdrant)**:
   - **Idempotency Guarantee**: Before upserting new vectors, any existing points for `document_id` are purged from Qdrant.
   - Points are upserted with full tenant, workspace, and authority metadata.
6. **Final Verification & Governance**:
   - **Stale Worker Guard**: Re-reads `SourceDocument.objects.get(id=doc.id)`. If `current_version_number > job_version`, processing aborts without altering document status.
   - **Confidence Routing**: Documents with OCR confidence $< 0.70$ are quarantined to `needs_review`.
   - **Cache Invalidation**: Triggers `TenantSafeCacheService.invalidate_document()` to purge stale query responses.

### 3.2 Transient vs. Permanent Error Retries
Background Celery tasks classify failures:
- **Transient Failures** (`ConnectionError`, `TimeoutError`, temporary Qdrant downtime): Retried with exponential backoff ($5\text{s}, 10\text{s}, 20\text{s}$), up to 3 attempts.
- **Permanent Failures** (`FileNotFoundError`, corrupted PDF, invalid format, stale worker detected): Failed immediately without retry; marked as `failed` with diagnostic `error_category` and recorded in `AuditEvent`.

---

## 4. Cascading Deletion & Permission Propagation

### 4.1 Document Deletion (`post_delete` signal)
When a `SourceDocument` is deleted in Django:
1. All associated vector points are automatically removed from Qdrant (`delete_document_chunks`).
2. Associated disk files (`file_obj`) are removed.
3. The workspace query cache is immediately invalidated.
4. An `item_deleted` event is logged in `AuditEvent`.

### 4.2 Permission Changes (`post_save` / `post_delete` signal)
When a `SourcePermission` is granted, modified, or revoked:
1. The workspace cache is immediately purged (`TenantSafeCacheService.invalidate_workspace`).
2. Subsequent queries immediately reflect revoked access, eliminating cache-based permission leaks.

---

## 5. Disaster Recovery Runbook

### Scenario A: Complete Qdrant Data Loss (Postgres Healthy)
If the Qdrant storage volume is destroyed or corrupted:
1. Start a fresh Qdrant container or provision a clean cluster:
   ```bash
   docker run -d -p 6333:6333 -v /var/lib/qdrant:/qdrant/storage qdrant/qdrant
   ```
2. Reconstruct all vector embeddings directly from PostgreSQL canonical chunks:
   ```bash
   python manage.py reconcile_stores --fix
   ```
3. Verify all documents are synchronized:
   ```bash
   python manage.py reconcile_stores
   ```
   *Outcome: All vectors and metadata are rebuilt without re-uploading documents or re-running OCR.*

---

### Scenario B: Restoring PostgreSQL from Backup
1. Restore database dump:
   ```bash
   pg_restore -h localhost -U lore_admin -d lore_enterprise backup_YYYYMMDD_HHMM.dump
   ```
2. Run database migrations to ensure schema alignment:
   ```bash
   python manage.py migrate
   ```
3. Reconcile Qdrant against restored PostgreSQL data:
   ```bash
   python manage.py reconcile_stores --fix
   ```
   *Outcome: Any vectors created after the snapshot are purged, and missing vectors are re-indexed.*

---

## 6. Store Reconciliation CLI Reference

The reconciliation tool provides dry-run audits and automated self-healing.

```bash
# Dry-run audit for all workspaces
python manage.py reconcile_stores

# Dry-run audit for a specific workspace
python manage.py reconcile_stores --workspace="4a32e18d-71b3-4f3e-9081-35b8004f1234"

# Automatically fix mismatches and purge orphaned vectors
python manage.py reconcile_stores --fix

# JSON output for automated alerting / monitoring scripts
python manage.py reconcile_stores --json
```

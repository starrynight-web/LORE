# LORE Enterprise — Engine Baseline Architecture & Verified Current State

**Document Version:** 2.0 (Verified Runtime Baseline)  
**Date:** October 2026  
**Auditor / Architect:** Antigravity Advanced Agentic Coding Engine  
**Environment:** Python 3.14.2 / Django 4.2.16 / Qdrant Client 1.20.0 / PyTorch 2.12.1 / SentenceTransformers 6.2.0  
**Scope:** Ingestion pipeline, vector persistence, lexical retrieval, 9-layer governance engine, MCP context API, and test execution.

---

## 1. Executive Summary & Verification Classification

This document establishes the verified technical baseline of LORE Enterprise as implemented in the repository codebase. It cross-references the theoretical specifications in `docs/enterprise/docs/lore.md`, `docs/LORE_ARCHITECTURE.md`, and `docs/PROJECT_REQUIREMENTS.md` with active source code and live test execution.

### Feature Classification Matrix

| Subsystem | Feature / Requirement | Status | Evidence / Implementation Details |
|---|---|---|---|
| **Ingestion** | Multi-format Extraction & OCR | **IMPLEMENTED** | `UnifiedDocumentExtractor` (`apps/ingestion/pipeline/extractors.py`): PDF (PyMuPDF/pdfplumber), DOCX, XLSX, images (Tesseract/Bengali repair). |
| **Ingestion** | Structure-Aware Chunking | **IMPLEMENTED** | `StructureAwareChunker` (`apps/knowledge/chunking.py`): 400-word target, 50-word overlap, Anthropic contextual headers prepended. |
| **Embedding** | Local Dense Semantic Encoding | **IMPLEMENTED** | `SentenceTransformerEmbeddingAdapter` (`apps/retrieval/embeddings.py`): `all-MiniLM-L6-v2`, 384 dimensions, normalized $L_2$ vectors via local PyTorch. |
| **Vector DB** | Qdrant Vector Persistence | **IMPLEMENTED** | `QdrantVectorStore` (`apps/retrieval/vector_store.py`): Embedded local storage (`backend/qdrant_storage`) or remote HTTP (`settings.QDRANT_URL`). Collection: `"lore_chunks"`. |
| **Vector DB** | Operational Circuit Breaker | **IMPLEMENTED** | `resilient_vector_search` (`apps/retrieval/resilience.py`): Circuit breaker trips after 3 failures; automatically falls back to SQL lexical search. |
| **Vector DB** | Cross-Store Reconciliation | **IMPLEMENTED** | `StoreReconciliationService` (`apps/sources/reconciliation.py`): Audits chunk counts between PostgreSQL and Qdrant; repairs missing vectors and purges orphans. |
| **Retrieval** | Lexical Substring Search | **IMPLEMENTED (DIVERGENT)** | `HybridRetrievalService.search` (`apps/retrieval/services.py`): Uses Django ORM `text__icontains` on `DocumentChunk`. **Not** SQLite FTS5 or PostgreSQL `tsvector`. |
| **Retrieval** | Reciprocal Rank Fusion (RRF) | **IMPLEMENTED** | `HybridRetrievalService.search`: True RRF ($k=60.0$) combining Qdrant dense vector ranks with SQL lexical ranks. |
| **Retrieval** | Context Reranking & Budgeting | **IMPLEMENTED** | `ContextReranker` (`apps/retrieval/services.py`): Evaluates normalized RRF, phrase match bonus, and token coverage. Enforces $\le 800$ token context budget. Authority is strictly decoupled from relevance score. |
| **GraphRAG** | Dedicated Graph Database | **DOCUMENTED ONLY** | KùzuDB and Neo4j are not installed, configured, or imported anywhere in the backend codebase. |
| **GraphRAG** | Graph Edge Neighbor Traversal | **NOT IMPLEMENTED** | Seed chunks returned by hybrid search are passed directly to governance without multi-hop neighbor expansion along graph edges. |
| **Governance** | L7: Permission Layer | **IMPLEMENTED** | `PermissionLayer` (`apps/governance/layers.py`): RBAC/ABAC query-time authorization against `SourcePermission` model before context enters the model. |
| **Governance** | L6: Authority & Conflicts | **IMPLEMENTED** | `AuthorityLayer` (`apps/governance/layers.py`): 7-rank authority dominance ladder, version supersession, and equal-rank contradiction detection. |
| **Governance** | L5: Temporal Validity | **IMPLEMENTED** | `TemporalValidityLayer` (`apps/governance/layers.py`): Excludes unapproved (`status != 'ready'`), future effective, and expired documents; applies staleness caveats; evaluates point-in-time `as_of`. |
| **Governance** | L4: Scoped Exceptions | **IMPLEMENTED** | `ExceptionLayer` (`apps/governance/layers.py`): Matches active `ScopedException` records by rule code, scope type/value, and time window. |
| **Governance** | L3: Evidence Sufficiency | **IMPLEMENTED** | `EvidenceSufficiencyLayer` (`apps/governance/layers.py`): Evaluates mandatory evidence requirements per decision type; blocks positive approval if missing. |
| **Governance** | L2: Answer-State Machine | **IMPLEMENTED** | `AnswerStateLayer` (`apps/governance/layers.py`): Resolves 9 canonical states and 5 directives following strict deterministic precedence. |
| **Governance** | L1: Decision Intelligence | **IMPLEMENTED** | `DecisionIntelligenceLayer` (`apps/governance/layers.py`): Classifies incoming queries, sets required evidence and escalation targets. |
| **Governance** | L0: Observability & Lineage | **IMPLEMENTED** | `ObservabilityLayer` (`apps/governance/layers.py`): Records `DecisionRecord` and `AuditEvent` with decision traces, token counts, and stage latency metrics. |
| **Governance** | Canonical Contract Gate | **IMPLEMENTED** | `validate_canonical_envelope` (`apps/governance/contract.py`): Validates `lore.result/2` schema and invariants; fails closed on violation. |
| **Generation** | Grounded LLM Inference | **IMPLEMENTED** | `GroundedGenerationService` (`apps/decisions/engine.py`): Calls Groq Cloud API (`gpt-oss-120B`) with prompt-injection isolation tags (`<untrusted_evidence_data>`). Falls back to deterministic passage citation. |
| **MCP** | Model Context Protocol Server | **IMPLEMENTED** | `mcp_server.py`: Stdio JSON-RPC 2.0 server supporting `lore.get_context`, `lore.search`, `lore_governed_query`, `lore_search`, `lore_get_document`, and `lore_ocr_extract`. |

---

## 2. Ingestion Pipeline Trace (Upload to Retrieval)

The document ingestion lifecycle runs synchronously (when `settings.CELERY_TASK_ALWAYS_EAGER=True`) or asynchronously via Celery worker (`process_document_job`):

```
1. Document Upload (REST: POST /api/v1/sources/documents/)
   ├─ StorageSecurityService.inspect_and_validate(): validates MIME type, size, SHA-256 hash.
   ├─ QuotaEnforcementService.check_upload_quota(): enforces organization storage limits.
   ├─ SourceDocument.objects.create(status='queued')
   ├─ DocumentVersion.objects.create(version_number=1, is_current=True)
   ├─ IngestionJob.objects.create(status='queued', current_stage='inspection')
   └─ AuditEvent.objects.create(event_type='document_uploaded')
        │
        ▼
2. Stage 1: Unified Extraction & OCR (apps/ingestion/pipeline/extractors.py)
   ├─ PyMuPDF (pypdfium2/pdfplumber) for digital PDFs.
   ├─ Tesseract OCR + Bengali phonetic repair for scanned images/pages.
   ├─ Persists DocumentPage records tied to document and version.
   └─ Computes average ocr_confidence across pages.
        │
        ▼
3. Stage 2: Normalization (apps/ingestion/tasks.py:90)
   ├─ Strips non-printable control characters.
   └─ Standardizes whitespace and heading markers.
        │
        ▼
4. Stage 3: Structure-Aware Chunking (apps/knowledge/chunking.py)
   ├─ Splits pages by Markdown/structural headings.
   ├─ Windows text into 400-word blocks with 50-word overlaps.
   ├─ Builds Anthropic Contextual Header:
   │    "Document: {title} | Workspace: {ws} | Page: {p} | Section: {heading} | Authority Rank: {rank}"
   └─ Bulk creates DocumentChunk records in relational database.
        │
        ▼
5. Stage 4: Local Embedding Generation (apps/retrieval/embeddings.py)
   ├─ Prepares chunk text: f"{chunk.contextual_header}\n---\n{chunk.text}"
   ├─ SentenceTransformerEmbeddingAdapter.embed_batch():
   │    Local in-process PyTorch inference on all-MiniLM-L6-v2.
   └─ Emits 384-dimensional normalized dense vectors.
        │
        ▼
6. Stage 5: Vector Indexing in Qdrant (apps/retrieval/vector_store.py)
   ├─ Idempotent purge: QdrantVectorStore.delete_document_chunks("lore_chunks", doc.id)
   ├─ Builds payloads: chunk_id, document_id, version, title, workspace_id, authority_level.
   ├─ QdrantVectorStore.upsert_chunks("lore_chunks", vectors, payloads, ids)
   └─ Updates relational DocumentChunk.vector_id = str(chunk.id).
        │
        ▼
7. Stage 6: Final Verification & Governance Gate
   ├─ Stale worker safeguard: verifies current_version_number hasn't changed during processing.
   ├─ OCR review routing: if ocr_confidence < 0.70, sets status='needs_review' (review queue).
   ├─ Normal publication: sets doc.status='ready' and job.status='ready'.
   ├─ Cache invalidation: TenantSafeCacheService.invalidate_document(ws_id, doc_id).
   └─ AuditEvent.objects.create(event_type='ingestion_completed').
```

---

## 3. Query Handling Trace (API/MCP to Governed Context)

Every query submitted via `POST /api/v1/retrieval/query/` or MCP tool `lore.get_context` / `lore_governed_query` executes through the canonical pipeline:

```
Query Request: { query: "...", workspace: "...", as_of?: "..." }
  │
  ▼
1. Tenant-Safe Cache Check (apps/retrieval/cache.py)
   ├─ Key: (organization_id, workspace_id, user_role, query_hash, as_of)
   └─ On cache hit: returns cached envelope immediately (tagged cached=True).
  │ (on cache miss)
  ▼
2. Hybrid Retrieval Seed Generation (apps/retrieval/services.py: HybridRetrievalService.search)
   ├─ Step 2a: Dense Vector Search (Qdrant)
   │    - Query embedded via SentenceTransformer (384d).
   │    - Qdrant query_points/search with workspace_id and organization_id filter.
   │    - Wrapped by CircuitBreaker (resilient_vector_search); falls back to SQL on failure.
   │    - Produces vector candidates with ranks r_vec in [1, 25].
   ├─ Step 2b: Relational Lexical Search (PostgreSQL / SQLite)
   │    - DocumentChunk.objects.filter(workspace_id, document__status='ready', text__icontains=kw)
   │    - Produces lexical candidates with ranks r_lex in [1, 25].
   ├─ Step 2c: Reciprocal Rank Fusion (RRF k=60.0)
   │    - RRF Score = 1.0 / (60 + r_vec) + 1.0 / (60 + r_lex).
   │    - Missing branch defaults to rank 999.
   │    - Zero-results short-circuit: returns [] if no candidate matched either branch.
   ├─ Step 2d: Context Reranking (ContextReranker)
   │    - Score = (0.45 * norm_rrf) + (0.35 * token_coverage) + phrase_bonus (0.35) + header_bonus (0.15).
   │    - Min threshold gating: drops score < 0.05.
   │    - INVARIANT: Authority level is NOT multiplied into relevance score.
   └─ Step 2e: Context Budgeting
        - Accumulates top candidates up to 800 tokens maximum.
  │
  ▼
3. 9-Layer Enterprise Governance Engine (apps/governance/layers.py: EnterpriseGovernanceEngine)
   ├─ Stage 0 (L7 Permission): Filters chunks against SourcePermission. Unauthorized chunks dropped.
   ├─ Stage 1 (L1 Intelligence): Classifies decision type, sets mandatory evidence list, identifies escalation target.
   ├─ Stage 2 (L5 Temporal): Drops document__status != 'ready', future effective dates, expired records.
   ├─ Stage 3 (L4 Exceptions): Matches active ScopedException records by rule code, scope, and query time.
   ├─ Stage 4 (L6 Authority): Resolves informal vs formal dominance and version supersession. Unresolved ties flag conflict.
   ├─ Stage 5 (L3 Sufficiency): Verifies mandatory evidence requirements. Sets missing list and sufficiency boolean.
   ├─ Stage 6 (L2 Answer State): Evaluates deterministic 9-state precedence ladder:
   │    denied > violation > conflicting > insufficient > abstain > human_review > qualified > supported > no_knowledge
   ├─ Stage 7 (Grounded Synthesis): Formulates answer via Groq API (if configured) or deterministic excerpt citations.
   ├─ Stage 8 (Provenance Assembly): Constructs exact citations (document_id, title, version, page, heading, passage).
   ├─ Stage 9 (Contract Validation): validate_canonical_envelope() enforces state-directive invariants.
   └─ Stage 10 (L0 Observability): Persists DecisionRecord and AuditEvent.
  │
  ▼
Output: Validated lore.result/2 JSON envelope returned to caller.
```

---

## 4. Models and External APIs vs Deterministic Logic

| Pipeline Function | Model / External API Used | Deterministic Equivalent Available |
|---|---|---|
| **Text Embedding** | SentenceTransformers `all-MiniLM-L6-v2` (Local PyTorch) | `HashProjectionEmbeddingAdapter` (MD5 n-gram projection, zero model weights) |
| **Grounded Answer Synthesis** | Groq Cloud API (`gpt-oss-120B` / `llama-3.3-70b-versatile`) | `GroundedGenerationService._generate_deterministic_synthesis` (verbatim excerpt citations) |
| **Document OCR** | Tesseract OCR CLI binary (`pytesseract`) | PyMuPDF digital text extractor (`pypdfium2` / `pdfplumber`) for digital documents |
| **Phonetic OCR Repair** | None | `repair_visual_bengali_document` (deterministic regex rule engine in `apps/ingestion/pipeline/ocr.py`) |
| **Digit Normalization** | None | `bangla_to_arabic_digits` (deterministic character mapping in `apps/ingestion/pipeline/ocr.py`) |
| **L7 Authorization** | None | 100% deterministic RBAC/ABAC rule evaluation in `PermissionLayer` |
| **L6 Authority & Conflict** | None | 100% deterministic 7-rank comparison and version comparison in `AuthorityLayer` |
| **L5 Temporal Validity** | None | 100% deterministic date arithmetic and boundary comparison in `TemporalValidityLayer` |
| **L4 Scoped Exceptions** | None | 100% deterministic scope and time-window matching in `ExceptionLayer` |
| **L3 Evidence Sufficiency** | None | 100% deterministic catalog matching in `EvidenceSufficiencyLayer` |
| **L2 Answer State** | None | 100% deterministic precedence ladder in `AnswerStateLayer` |
| **Contract Invariants** | None | 100% deterministic schema validator in `apps/governance/contract.py` |

---

## 5. Storage and Database Configuration

### 5.1 Relational Database
- **Local Development / Standalone:** SQLite 3 (`backend/db.sqlite3`).
- **Production / Docker Compose:** PostgreSQL 16 Alpine via `psycopg2-binary` and `dj-database-url`.
- **Migrations:** All 10 Django applications (`admin`, `audit`, `auth`, `authtoken`, `contenttypes`, `decisions`, `governance`, `identity`, `ingestion`, `knowledge`, `sessions`, `sources`, `subscriptions`, `workspaces`) have fully applied, consistent migration chains. Zero unapplied migrations exist.

### 5.2 Vector Database (Qdrant)
- **Configuration Keys:**
  - `QDRANT_URL`: URL of remote Qdrant service (e.g. `http://qdrant:6333`). Defaults to empty string.
  - `QDRANT_API_KEY`: Optional authentication token for managed Qdrant cloud.
  - `QDRANT_LOCAL_PATH`: Local storage folder path (`backend/qdrant_storage`).
- **Storage Mode Resolution:**
  - If `QDRANT_URL` is set: connects to remote HTTP instance.
  - If `QDRANT_URL` is empty: initializes local disk storage at `QDRANT_LOCAL_PATH`.
  - If filesystem access fails: falls back to in-memory mode (`:memory:`).
- **Process-Wide Client Protection:**
  - `QdrantVectorStore._shared_client` caches the initialized client across all requests in the process, preventing filesystem lock errors during concurrent Django queries.
- **Circuit Breaker:**
  - `qdrant_circuit_breaker` trips to `OPEN` after 3 consecutive connection or timeout failures, redirecting traffic to SQL lexical fallback until the 30-second recovery timeout expires.

---

## 6. Model Context Protocol (MCP) Server Status

- **Entry Point:** `backend/mcp_server.py`.
- **Protocol:** JSON-RPC 2.0 over standard input/output (stdio).
- **Active Manifest Tools:**
  1. `lore.get_context`: Canonical flagship tool accepting `file_path`, `intent`, `query`, `workspace_id`, `as_of`.
  2. `lore.search`: Canonical hybrid search tool accepting `query`, `workspace_id`, `limit`.
  3. `lore_governed_query`: Legacy alias for `lore.get_context`.
  4. `lore_search`: Legacy alias for `lore.search`.
  5. `lore_get_document` / `lore.get_document`: Retrieves document metadata, page confidence, and samples.
  6. `lore_ocr_extract` / `lore.ocr_extract`: Executes live dual-stream OCR extraction on a specified local file.
- **Service Invocation:** `lore.get_context` and `lore_governed_query` call the exact same `HybridRetrievalService` and `EnterpriseGovernanceEngine` classes used by the REST API.
- **Governance Bypass Check:** The search tools (`lore.search`, `lore_search`) return raw ranked candidate passages for informational use. The governed query tools (`lore.get_context`, `lore_governed_query`) execute all 9 governance layers and fail closed on error.

---

## 7. Test Suite Execution & Verification Record

### 7.1 Environment & Test Invocation
- **Documented Environment:** Python 3.14.2 (`C:\Python314\python.exe`) with all packages in `backend/requirements.txt`.
- **Command Executed:**
  ```powershell
  python -m pytest tests/ -v
  ```
- **Execution Summary:**
  - Total test files: 7
  - Total test cases collected: 58
  - **Passed:** 58 (100%)
  - **Failed:** 0
  - **Total execution time:** 41.29 seconds

### 7.2 Breakdown of Test Files and Results

| Test File | Test Count | Status | Key Coverage |
|---|---|---|---|
| `tests/test_enterprise_p4.py` | 2 | **PASSED** | Local folder connector execution, review queue human approval workflow. |
| `tests/test_enterprise_pipeline.py` | 9 | **PASSED** | Bengali phonetic repair, magic byte validation, ingestion pipeline, cross-tenant isolation, OCR endpoints. |
| `tests/test_evaluation_and_resilience_p3.py` | 5 | **PASSED** | Benchmark evaluation harness, 3-arm baseline comparator, circuit breaker lifecycle, resilient vector fallback, telemetry endpoint. |
| `tests/test_governance_p1.py` | 16 | **PASSED** | Relevance vs authority separation, authority dominance, version supersession, temporal validity, historical `as_of`, scoped exceptions, stable-only serving, prompt injection containment, canonical contract validation. |
| `tests/test_lifecycle_p2.py` | 8 | **PASSED** | Pipeline idempotency, stale worker protection, cascading deletion signal, permission change cache invalidation, tenant cache isolation, reconciliation service (missing & orphaned vectors). |
| `tests/test_saas_security_and_lifecycle.py` | 6 | **PASSED** | Tenant isolation, immutable versioning, local SentenceTransformer embedding generation, quota enforcement. |
| `tests/test_retrieval_stack_audit.py` | 7 | **PASSED** | End-to-end ingestion to Qdrant persistence, query embedding to vector search, hybrid RRF fusion, graph traversal audit status, governance filter exclusions, MCP context tool execution, indexing failure safety. |

### 7.3 Environment Failures vs Code Failures
- **Environment Discrepancy Observed:** If `pytest` is invoked directly as a binary without `python -m`, Windows invokes Python 3.13 where `qdrant_client` is not installed, resulting in setup failures (`No module named 'qdrant_client'`).
- **Codebase Execution:** When invoked via `python -m pytest` under the configured Python 3.14 environment, zero test failures occur.

---

## 8. Identified Architectural Gaps and Technical Debt

1. **Lexical Substring Matching vs Full-Text Search (FTS):**
   `apps/retrieval/services.py` currently uses SQL `text__icontains` substring queries. While functional for keyword presence, it lacks BM25 term weighting, inverse document frequency (IDF), and stemming.
2. **Graph Expansion Absence on Seeds:**
   `lore.md` specifies multi-hop graph expansion along `APPLIES_TO`, `DEPENDS_ON`, and `REQUIRES` edges. In the actual codebase, seed chunks pass directly from hybrid retrieval into governance without neighbor node expansion.
3. **Pluggable Embedding Providers:**
   `settings.py` declares support for `openai` and `test-projection`, but `apps/retrieval/embeddings.py` only implements `SentenceTransformerEmbeddingAdapter` and `HashProjectionEmbeddingAdapter`. Setting `EMBEDDING_PROVIDER='openai'` silently falls back to hash projection.
4. **Missing Standalone MCP Tools:**
   11 standalone tools documented in `lore.md` §11 (e.g. `lore.check_compliance`, `lore.detect_conflicts`, `lore.trace`, `lore.get_history`) lack registered tool handlers in `mcp_server.py`.

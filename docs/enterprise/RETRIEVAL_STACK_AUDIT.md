# LORE Retrieval Stack Audit: Embeddings, Vector DB, RAG, GraphRAG, and MCP

**Audit Date:** October 2026  
**Auditor:** Antigravity Advanced Agentic Coding Engine  
**Codebase Version:** LORE Enterprise 2.0 (Django 4.2.16 / Python 3.14.2)  
**Verification Scope:** Document ingestion, local/remote vector storage, lexical search, hybrid fusion, graph expansion, 9-layer governance engine, MCP context API, and test harnesses.

---

## Executive Summary & Component Status Matrix

This audit verifies the actual runtime implementation of the LORE Enterprise retrieval and governance stack against its specifications and documentation (`docs/enterprise/docs/lore.md`, `docs/LORE_ARCHITECTURE.md`, `docs/PROJECT_REQUIREMENTS.md`).

Every assertion in this report is backed by direct code inspection and live integration test execution against the local database and Qdrant storage.

| Component / Subsystem | Claimed in `lore.md` | Actual Code Implementation | Status | Audit Verdict |
|---|---|---|---|---|
| **Embedding Generation** | Local 384d / MiniLM / Intel | `SentenceTransformerEmbeddingAdapter` (`all-MiniLM-L6-v2`) via PyTorch | **ACTIVE** | Genuinely generates 384d normalized vectors locally. |
| **Vector Database** | `sqlite-vec` (local) / Qdrant (cluster) | Qdrant (`QdrantVectorStore`), embedded filesystem (`/qdrant_storage`) or HTTP | **ACTIVE** | Genuinely upserts, counts, searches, deletes, and reconciles vectors. |
| **Lexical Retrieval** | SQLite FTS5 / BM25 index | Django ORM `text__icontains` on PostgreSQL/SQLite `DocumentChunk` table | **ACTIVE / DIVERGENT** | Works, but uses SQL `icontains` substring matching, NOT SQLite FTS5 or BM25. |
| **Hybrid Search & Fusion** | Reciprocal Rank Fusion (RRF) | `(1.0 / (60 + r_vec)) + (1.0 / (60 + r_lex))` + `ContextReranker` | **ACTIVE** | Genuine RRF (k=60) combining Qdrant + SQL ranks; separate reranker. |
| **Graph Database** | KùzuDB / Neo4j temporal graph | Relational Django tables (`SourceDocument`, `DocumentVersion`, `ConflictRecord`, `ScopedException`) | **NOT IMPLEMENTED** | No graph database engine (KùzuDB/Neo4j) is installed or configured. |
| **Graph Expansion (GraphRAG)**| Multi-hop traversal along `APPLIES_TO`, `DEPENDS_ON`, `REQUIRES` | Retrieval returns vector + lexical seeds directly without neighbor expansion | **NOT IMPLEMENTED** | Seed items are NOT expanded via graph query or edge traversal. |
| **9-Layer Governance Engine** | L7 -> L0 evaluation machine | `EnterpriseGovernanceEngine` in `apps/governance/layers.py` | **ACTIVE** | Fully enforces L7 permissions, L5 dates, L4 exceptions, L6 conflicts, L3 sufficiency, L2 states. |
| **Grounded LLM Generation** | Groq `gpt-oss-120B` / Deterministic | `GroundedGenerationService` with Groq API call or deterministic synthesis | **ACTIVE** | Live calls Groq if API key provided; otherwise runs deterministic passage citation. |
| **MCP Server Protocol** | 15 `lore.*` tools (`lore.get_context`, etc.) | Stdio JSON-RPC with 4 `lore_*` tools (`lore_search`, `lore_governed_query`, `lore_get_document`, `lore_ocr_extract`) | **PARTIAL** | Core governed retrieval works via `lore_governed_query`, but 12 documented tools and dot-notation naming are missing. |

---

## 1. Embedding Subsystem Audit

### 1.1 Ingestion Pipeline: Text to Vector Trace
The path from extracted document text to persisted vector embedding is executed in `apps/ingestion/tasks.py`:

```
Uploaded Document (PDF / DOCX / TXT / Image)
  │
  ▼
Stage 1: UnifiedDocumentExtractor.extract_document() [apps/ingestion/pipeline/extractors.py]
  │  Produces pages_data with page_number, text, confidence, engine.
  │  Persists DocumentPage records in relational database.
  ▼
Stage 3: StructureAwareChunker.chunk_document_pages() [apps/knowledge/chunking.py]
  │  Target chunk size: 400 words (overlap: 50 words).
  │  Appends Anthropic Contextual Header:
  │    "Document: {title} | Workspace: {ws} | Page: {p} | Section: {heading} | Authority Rank: {rank}"
  │  Persists DocumentChunk records in PostgreSQL/SQLite.
  ▼
Stage 4: Embeddings Generation [apps/ingestion/tasks.py:136-146]
  │  Constructs embed_texts: [f"{chunk.contextual_header}\n---\n{chunk.text}"]
  │  Calls get_embedding_adapter().embed_batch(embed_texts)
  ▼
Stage 5: Vector Indexing in Qdrant [apps/ingestion/tasks.py:149-191]
  │  Idempotent cleanup: QdrantVectorStore.delete_document_chunks("lore_chunks", doc.id)
  │  Constructs payload: chunk_id, document_id, version, title, workspace_id, authority_level
  │  Calls QdrantVectorStore.upsert_chunks("lore_chunks", vectors, payloads, ids)
  │  Updates DocumentChunk.vector_id = str(chunk.id)
  ▼
Stage 6: Final Verification & Governance
     Checks OCR confidence, stale worker overwrite, and marks SourceDocument status = 'ready'
```

### 1.2 Embedding Interface & Provider Configuration
- **Interface:** `BaseEmbeddingAdapter` (`apps/retrieval/embeddings.py` line 9):
  - `dimension: int = 384`
  - `embed_text(self, text: str) -> List[float]`
  - `embed_batch(self, texts: List[str]) -> List[List[float]]`
- **Active Implementation:** `SentenceTransformerEmbeddingAdapter`:
  - Model name: `all-MiniLM-L6-v2` (configured via `settings.EMBEDDING_MODEL_NAME`).
  - Provider: `sentence-transformers` (`settings.EMBEDDING_PROVIDER`).
  - Dimension: **384 dense floats**.
  - Normalization: `normalize_embeddings=True` (cosine similarity = dot product).
  - Caching: Class-level singleton `_model_instance` avoids reloading model weights per request.
- **Inference Location:** **100% Local Inference**.
  - Runs in-process via PyTorch (`torch 2.12.1`) and Hugging Face `sentence-transformers 6.2.0`.
  - Zero external network dependencies for embedding inference; zero per-token API cost.
- **Deterministic Fallback:** `HashProjectionEmbeddingAdapter`:
  - MD5 n-gram projection into 384-dimensional space with L2 normalization. Used as benchmark and fallback if `sentence-transformers` fails to import.
- **Configuration Gap Identified:**
  - `settings.py` mentions `# Providers: 'sentence-transformers', 'openai', 'test-projection'`, but **no OpenAI embedding adapter exists in `embeddings.py`**. If `EMBEDDING_PROVIDER='openai'` is set, the factory silently falls back to `HashProjectionEmbeddingAdapter`.

### 1.3 Chunk Provenance & Mapping
- Every vector in Qdrant is assigned a point ID matching the relational `DocumentChunk.id` (UUID string).
- The vector payload contains full provenance:
  `chunk_id`, `document_id`, `document_version`, `document_title`, `organization_id`, `workspace_id`, `collection_id`, `page_number`, `heading_path`, `authority_level`, `text` (first 300 chars).
- The relational model stores `DocumentChunk.vector_id = str(chunk.id)`.

### 1.4 Re-Ingestion, Idempotency & Stale Worker Protection
- **Idempotency:** When re-ingesting a document, `apps/ingestion/tasks.py:157` deletes all existing vectors in Qdrant matching `document_id` before upserting the newly generated chunk vectors.
- **Relational Cleanup:** Old `DocumentChunk` and `DocumentPage` records are purged atomically via `DocumentChunk.objects.filter(document=doc).delete()`.
- **Stale Worker Safeguard:** Line 199 verifies `fresh_doc.current_version_number <= doc_version.version_number`. If a newer version was uploaded while the worker processed an older job, the job is aborted with `STALE_VERSION_OVERWRITE_PREVENTED`.

### 1.5 Failure State Behavior
- If an exception occurs during embedding or indexing (Stage 4 or 5):
  - `tasks.py:262-285` catches the exception.
  - `job.status` is set to `'failed'`.
  - `doc.status` is set to `'failed'`.
  - An audit event `ingestion_failed` is persisted.
  - The document is **never published as `'ready'`**.
  - During retrieval, `HybridRetrievalService` explicitly filters `document__status='ready'`.
  - In L5 governance, `TemporalValidityLayer` rejects any chunk whose document is not `'ready'`.
  - **Verdict:** Embedding failures cannot leave a document in a published or retrievable state.

### 1.6 Query Embedding Audit
- Query embedding is performed in `HybridRetrievalService.search()` (`apps/retrieval/services.py:174`):
  `query_vec = self.embedder.embed_text(query)`
- `self.embedder` is instantiated via `get_embedding_adapter()`, guaranteeing identical model (`all-MiniLM-L6-v2`) and dimension (384) as the document chunks.

---

## 2. Vector Database Audit (Qdrant)

### 2.1 Active Implementation vs Mere Configuration
Qdrant is **actively integrated and used in runtime execution**:
- Code entry point: `apps/retrieval/vector_store.py` (`QdrantVectorStore`).
- Shared Client: Implements a process-wide `_shared_client` singleton to prevent local file locks when multiple instances are initialized within Django.
- Dual Storage Modes:
  1. **Remote Qdrant Service:** If `settings.QDRANT_URL` is set (e.g. `http://qdrant:6333` in Docker Compose), connects over HTTP with optional API key.
  2. **Local Embedded Storage:** If `QDRANT_URL` is empty, uses `qdrant_client.QdrantClient(path=settings.QDRANT_LOCAL_PATH)` storing directly to `./backend/qdrant_storage/`.
  3. **In-Memory Fallback:** Falls back to `QdrantClient(":memory:")` if local directory access fails.

### 2.2 Operations Code Reference
- **Collection Setup:** `_ensure_collection(collection_name)` (`vector_store.py:68`):
  Creates collection `"lore_chunks"` with `VectorParams(size=384, distance=Distance.COSINE)`.
- **Write Vectors:** `upsert_chunks(collection_name, vectors, payloads, ids)` (`vector_store.py:86`):
  Batches `PointStruct` objects and calls `client.upsert()`.
- **Search Vectors:** `search(collection_name, query_vector, filter_dict, limit)` (`vector_store.py:104`):
  Uses `query_points()` (modern Qdrant client) or `search()`.
- **Delete Vectors:** `delete_document_chunks(collection_name, document_id)` (`vector_store.py:150`):
  Uses `client.delete(points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))]))`.
- **Count Chunks:** `count_document_chunks(collection_name, document_id)` (`vector_store.py:165`):
  Uses `client.count()` with `document_id` filter.
- **List All Document IDs:** `list_indexed_document_ids(collection_name)` (`vector_store.py:182`):
  Scrolls through points in batches of 250 without loading vector payloads.

### 2.3 Filters Applied at Vector Engine Level
- In `HybridRetrievalService.search()` (`services.py:175-182`):
  - Mandatory: `workspace_id`, `organization_id`.
  - Optional: `collection_id`, `document_id`.
- **Architectural Caveat:**
  Permission checks (L7), publication status (`status='ready'`), and temporal expiry (L5) are **not filtered within Qdrant payloads**. Instead, Qdrant returns candidate chunks, and LORE's downstream governance layers (`PermissionLayer`, `TemporalValidityLayer`) filter out unauthorized, draft, quarantined, or expired documents in Python.

### 2.4 Resilience, Timeouts & Circuit Breaker
- In `apps/retrieval/resilience.py`:
  - `qdrant_circuit_breaker = CircuitBreaker("qdrant_vector_store", failure_threshold=3, recovery_timeout=30.0)`.
  - `resilient_vector_search()` wraps all calls to `vector_store.search()`.
  - If Qdrant throws connection errors, timeouts, or the circuit trips to `OPEN`, the request automatically invokes `_execute_fallback()`.
  - Fallback queries `DocumentChunk.objects.filter(document__status='ready', text__icontains=kw)`, tagging results with `fallback_mode='lexical_only'` and `circuit_breaker_active=True`.

### 2.5 Cross-Store Reconciliation Service
- `StoreReconciliationService.reconcile()` (`apps/sources/reconciliation.py`):
  - Scans published documents in PostgreSQL (`status__in=['ready', 'needs_review']`).
  - Compares `postgres_chunk_count` vs `vstore.count_document_chunks()`.
  - When `fix=True`, automatically re-embeds missing chunks and upserts them to Qdrant.
  - Identifies and purges orphaned vectors in Qdrant whose parent documents were deleted or inactivated in PostgreSQL.

---

## 3. Lexical Retrieval and Hybrid RAG Audit

### 3.1 Lexical Retrieval Implementation
- Code location: `HybridRetrievalService.search()` (`apps/retrieval/services.py:204-228`).
- **Underlying Database:** Relational SQL database (SQLite in standalone dev, PostgreSQL in Docker/production).
- **Matching Mechanism:** Django ORM `text__icontains=kw` for the first 6 query tokens (length > 1).
- **Publication Gating:**
  ```python
  lexical_qs = DocumentChunk.objects.filter(
      workspace_id=workspace_id,
      organization_id=organization_id,
      document__status='ready'
  ).exclude(
      document__status__in=['quarantined', 'failed', 'needs_review', 'uploaded']
  )
  ```
- **Finding:** Lexical search is relational substring matching (`LIKE '%token%'`). It is **not** SQLite FTS5, not PostgreSQL `tsvector`/`tsquery`, and not BM25 index.

### 3.2 Hybrid Fusion & Reciprocal Rank Fusion (RRF)
- LORE genuinely executes hybrid search:
  1. Dense vector search via Qdrant returns vector candidates with rank $r_{vec} \in [1, 25]$.
  2. Relational lexical search returns text candidates with rank $r_{lex} \in [1, 25]$.
  3. Combined candidate pool: `all_chunk_ids = set(vector_ranks.keys()) | set(lexical_ranks.keys())`.
  4. Formula implemented:
     $$\text{RRF Score} = \frac{1.0}{k + r_{vec}} + \frac{1.0}{k + r_{lex}} \quad (k = 60.0)$$
     If a candidate is absent from one branch, its rank defaults to 999.
- **Zero Hallucination Gating:** If `all_chunk_ids` is empty, search returns an empty list immediately. It never injects unrelated high-authority chunks into empty results.

### 3.3 Context Reranking
- Implemented in `ContextReranker` (`apps/retrieval/services.py:25-144`):
  - Normalized RRF component: $\text{norm\_rrf} \times 0.45$.
  - Exact phrase match bonus: $+0.35$ if the multi-word query appears verbatim in chunk text, header, or title.
  - Token coverage ratio: $\text{coverage} \times 0.35$ (fraction of query tokens present in chunk).
  - Contextual header bonus: $+0.15$ if section/heading tokens match.
  - Threshold gating: Chunks with `relevance_score < min_relevance_threshold` (default 0.05) are dropped.
- **Critical Architectural Invariant:** Authority rank is **strictly excluded** from relevance scoring. Authority cannot make an irrelevant chunk relevant.

### 3.4 Context Budgeting
- Budget: $\le 800$ tokens (`services.py:267-274`).
- Chunks are accumulated in descending order of reranked relevance score until the 800-token threshold is reached.

### 3.5 Retrieval Followed by Governed Context vs Model Generation
LORE supports both modes:
1. **Governed Context Envelope (External AI Advisor):** Returned to external agents via MCP (`lore_governed_query`) or REST API (`POST /api/v1/retrieval/query/`). Contains typed state, directive, evidence found, evidence missing, resolved conflicts, and citations.
2. **Model-Generated Answers:** In `apps/decisions/engine.py` (`GroundedGenerationService`):
   - **Groq Cloud API (`gpt-oss-120B` / `llama-3.3-70b-versatile`):** If a Groq API key is provided, invokes Groq at `temperature=0.0`. Uses strict prompt-injection isolation: raw documents are enclosed in `<untrusted_evidence_data>` tags and forbidden from overriding instructions.
   - **Grounded Deterministic Synthesis:** If no LLM key is configured, formats verbatim excerpt citations with Rev number, Page number, and Authority Rank.

---

## 4. GraphRAG Audit

### 4.1 Search for Graph Database & Models
An exhaustive search was conducted across all files in the repository:
- `kuzu`, `kuzudb`: 0 matches in code (only in `docs/`).
- `neo4j`: 0 matches in code (only in `docs/`).
- `networkx`: Installed in Python environment, but not imported in `backend/apps/`.
- No graph database service is declared in `docker-compose.yml` (services are: `backend`, `celery_worker`, `frontend`, `db` (Postgres), `redis`, `qdrant`, `minio`).

### 4.2 Audit of Graph Relationships
The status of relationships documented in `lore.md` and architecture specifications:

| Relationship | Claimed in Spec | Actual Implementation | Classification |
|---|---|---|---|
| `APPLIES_TO` | Rule $\to$ Component/File | Mentioned in docs; no model or database field | **DOCUMENTED ONLY** |
| `DEPENDS_ON` | Rule $\to$ Rule dependency | Mentioned in docs; no model or database field | **DOCUMENTED ONLY** |
| `SUPERSEDES` | Version $\to$ Version temporal chain | Implemented via `DocumentVersion.version_number` and `SourceDocument.current_version_number`. Evaluated in Python logic in `AuthorityLayer` (`pos_ver > neg_ver`). | **RELATIONAL / LOGICAL** |
| `CONFLICTS_WITH` | Rule $\leftrightarrow$ Rule contradiction | Implemented via relational model `ConflictRecord` (`source_a`, `source_b`, `resolution_status`). | **RELATIONAL TABLE** |
| `FROM` / `DERIVED_FROM` | Chunk $\to$ Document Version | Implemented via `DocumentChunk.document` and `DocumentChunk.document_version` foreign keys. | **RELATIONAL FK** |
| `OVERRIDES` | Exception $\to$ Rule within scope | Implemented via relational model `ScopedException` (`rule_code`, `scope_type`, `scope_value`, `window_start/end`). | **RELATIONAL TABLE** |
| `GOVERNED_BY` | Document $\to$ Access Policy | Implemented via relational model `SourcePermission` (`document`, `access_level`, `allowed_roles`). | **RELATIONAL TABLE** |
| `REQUIRES` | Decision $\to$ Evidence Requirement | Implemented via relational model `EvidenceRequirement` (`decision_type`, `evidence_type`, `min_authority_level`). | **RELATIONAL TABLE** |

### 4.3 Retrieved Seed Graph Expansion
- In `HybridRetrievalService.search()`, candidates returned by Qdrant and SQL lexical search are **NOT expanded via graph traversal**.
- There is no Cypher query, no recursive SQL CTE, no adjacency list traversal, and no multi-hop edge fetch.
- Candidates pass directly into the 9-layer governance engine without graph neighbor expansion.
- **Verdict:** GraphRAG in the current implementation is **PARTIAL / RELATIONAL ONLY**. Graph relationships exist as relational foreign keys and lookup tables, but graph traversal/expansion is not executed during retrieval.

### 4.4 Comparison with `lore.md`
`docs/enterprise/docs/lore.md` describes:
- Graph store: KùzuDB.
- Vector store: `sqlite-vec`.
- Lexical store: SQLite FTS5.

**Reality vs Documentation:**
- LORE was implemented using **Qdrant** for vectors (significantly more robust and scalable than `sqlite-vec`), **PostgreSQL/SQLite** for relational governance entities, and **Django ORM** for lexical filtering.
- **Recommendation:** Do NOT rip out Qdrant to install `sqlite-vec`. Qdrant provides enterprise multi-tenancy, filtering, and distributed clustering that `sqlite-vec` lacks. For graph capabilities, implement an explicit relational edge adjacency table (or lightweight NetworkX / SQLite recursive CTEs) to traverse `SUPERSEDES`, `CONFLICTS_WITH`, and `REQUIRES` edges during retrieval.

---

## 5. MCP and AI Advisor Audit

### 5.1 MCP Server Entry Point
- Entry Point: `backend/mcp_server.py`.
- Protocol: JSON-RPC 2.0 over standard I/O (stdio).
- Protocol Version: `2024-11-05`.
- Server Name: `lore-enterprise-mcp` v2.0.0.

### 5.2 Registered Tools in Implementation
The MCP manifest (`TOOLS_MANIFEST` in `mcp_server.py:59`) registers 4 tools:
1. `lore_search`: Performs hybrid vector + lexical search across workspace knowledge.
2. `lore_governed_query`: Flagship governed retrieval tool (the current equivalent of `lore.get_context`). Executes hybrid search, 9-layer governance evaluation, and returns `lore.result/2` JSON envelope.
3. `lore_get_document`: Returns document metadata, OCR confidence, and sample pages.
4. `lore_ocr_extract`: Runs live dual-stream OCR extraction on a specified local file.

### 5.3 Governance Enforcement & Bypass Audit
- Does `lore_governed_query` invoke the governance engine?
  - **YES.** Lines 214-223 call `EnterpriseGovernanceEngine.evaluate()`.
  - Enforces L7 permissions, L1 classification, L5 temporal validity, L4 exceptions, L6 authority, L3 sufficiency, and L2 state resolution.
- Does any tool bypass governance?
  - `lore_search` returns raw ranked passages without the 9-state governance envelope. This is intended as an informational search tool, but AI clients should use `lore_governed_query` for actionable decisions.
  - In `EnterpriseGovernanceEngine.evaluate()`, unhandled exceptions invoke `fail_closed_envelope()`, returning `state='violation'`, `directive='stop'` with zero leaked content.
  - **Verdict:** No governance bypass exists in the governed query path.

### 5.4 Documented Tools vs Actual Implementation Matrix
Section 11 of `docs/enterprise/docs/lore.md` specifies 15 MCP tools under the `lore.<tool>` namespace:

| Tool Name in `lore.md` §11 | Status in Codebase | Implementation Details / Gap |
|---|---|---|
| `lore.get_context` | **EXISTING (RENAMED)** | Implemented as `lore_governed_query`. Accepts `query`, `workspace_id`, `groq_api_key`, `llm_model`. Missing `file_path` param and dot notation alias. |
| `lore.search` | **EXISTING (RENAMED)** | Implemented as `lore_search`. Accepts `query`, `workspace_id`, `limit`. |
| `lore.get_document` | **EXISTING (EXTRA)** | Implemented as `lore_get_document`. (Not listed in `lore.md` §11, but present in MCP server). |
| `lore.ocr_extract` | **EXISTING (EXTRA)** | Implemented as `lore_ocr_extract`. (Not listed in `lore.md` §11, but present in MCP server). |
| `lore.bootstrap` | **MISSING** | Not implemented in `mcp_server.py`. |
| `lore.check_compliance` | **MISSING** | Evaluator exists in REST views/layers, but no MCP tool entry point is registered. |
| `lore.get_skill` | **MISSING** | `KnowledgeItem(item_type='skill')` model exists, but no MCP tool is registered. |
| `lore.detect_conflicts` | **MISSING** | Conflict logic exists in `AuthorityLayer`, but no standalone MCP tool is registered. |
| `lore.trace` | **MISSING** | Decision traces exist in `DecisionRecord`, but no standalone MCP lookup tool is registered. |
| `lore.log_decision` | **MISSING** | Decisions logged automatically by L0, but no explicit agent-facing tool is registered. |
| `lore.get_history` | **MISSING** | `DocumentVersion` model exists, but no MCP tool is registered. |
| `lore.stats` | **MISSING** | Telemetry endpoint exists in REST, but no MCP tool is registered. |
| `lore.check_evidence_sufficiency` | **MISSING** | Implemented as L3 layer internally, but no standalone MCP tool is registered. |
| `lore.get_authority_info` | **MISSING** | Implemented as L6 layer internally, but no standalone MCP tool is registered. |
| `lore.query_as_of` | **MISSING** | Supported as parameter `as_of` in `lore_governed_query`, but not as standalone tool. |
| `lore.get_active_exceptions` | **MISSING** | `ScopedException` model exists, but no standalone MCP query tool is registered. |
| `lore.escalate_to_human` | **MISSING** | Review queue model exists, but no standalone MCP tool is registered. |

---

## 6. End-to-End Test Execution and Output

A dedicated, comprehensive audit test suite was created in `backend/tests/test_retrieval_stack_audit.py` covering all 7 audit areas. All tests run against active Django and Qdrant instances without mock bypasses.

### Test Command
```powershell
python -m pytest tests/test_retrieval_stack_audit.py -v -s
```

### Actual Live Test Output
```
============================= test session starts =============================
platform win32 -- Python 3.14.2, pytest-9.0.2, pluggy-1.6.0 -- C:\Python314\python.exe
cachedir: .pytest_cache
django: version: 4.2.16, settings: lore_enterprise.settings (from ini)
rootdir: E:\LORE\backend
configfile: pytest.ini
plugins: anyio-4.14.1, Faker-40.8.0, cov-5.0.0, django-4.9.0
collecting ... collected 7 items

tests/test_retrieval_stack_audit.py::TestRetrievalStackAudit::test_01_document_ingestion_to_vector_persistence 
PASSED [ 14%]
tests/test_retrieval_stack_audit.py::TestRetrievalStackAudit::test_02_query_embedding_and_vector_search 
PASSED [ 28%]
tests/test_retrieval_stack_audit.py::TestRetrievalStackAudit::test_03_hybrid_retrieval_and_rrf_fusion 
PASSED [ 42%]
tests/test_retrieval_stack_audit.py::TestRetrievalStackAudit::test_04_graph_traversal_audit_status 
PASSED [ 57%]
tests/test_retrieval_stack_audit.py::TestRetrievalStackAudit::test_05_governance_filters_prevent_unauthorized_and_unpublished 
PASSED [ 71%]
tests/test_retrieval_stack_audit.py::TestRetrievalStackAudit::test_06_mcp_context_tool_returns_governed_result 
PASSED [ 85%]
tests/test_retrieval_stack_audit.py::TestRetrievalStackAudit::test_07_indexing_failures_and_stale_vectors_safe 
PASSED [100%]

============================= 7 passed in 19.07s ==============================
```

### Live MCP Server Self-Test Output
Executed via `python backend/mcp_server.py --test`:
```json
{
  "schema": "lore.result/2",
  "status": "supported",
  "directive": "proceed_and_cite",
  "answer": "According to landtech_hackathon_rulebook (Rev 1, Page 4, Authority Rank 3):\n> \"LandTech 2026 Innovation Hackathon Rule Book (v1.2)...\"",
  "decision_type": "general_inquiry",
  "escalation_target": "workspace_admin",
  "evidence_missing": [],
  "conflicts_resolved": [],
  "exceptions_applied": [],
  "layers_breakdown": {
    "l7_permission": { "status": "passed", "denials": [] },
    "l1_decision_intelligence": { "decision_type": "general_inquiry", "escalation": "workspace_admin", "risk": "low" },
    "l6_authority": { "conflicts_count": 0, "unresolved_tie": false },
    "l5_temporal": { "stale_data": false, "temporal_notes": [] },
    "l4_exceptions": { "applied_count": 0, "exceptions": [] },
    "l3_sufficiency": { "is_sufficient": true, "missing_count": 0 },
    "l2_answer_state": { "final_state": "supported", "directive": "proceed_and_cite" },
    "l0_observability": {
      "trace_id": "trace-628395ef9988",
      "timings_ms": {
        "l7_permission_ms": 1.218,
        "l1_intelligence_ms": 0.023,
        "l5_temporal_ms": 1.38,
        "l4_exception_ms": 1.147,
        "l6_authority_ms": 0.51,
        "l3_sufficiency_ms": 0.083
      }
    }
  },
  "anti_hallucination_active": true,
  "citations_count": 3,
  "trace_id": "trace-628395ef9988"
}
```

---

## 7. Differences Between Implementation and `lore.md`

| Dimension | `lore.md` Specification | Actual Implementation in Codebase | Architectural Evaluation |
|---|---|---|---|
| **Vector Engine** | `sqlite-vec` local virtual table | Qdrant (embedded local filesystem or remote service) | **Superior.** Qdrant offers production payload filtering, clustering, and persistence that `sqlite-vec` lacks. |
| **Lexical Search** | SQLite FTS5 with BM25 ranking | Django ORM SQL `text__icontains` substring match | **Divergence.** Current SQL `icontains` lacks BM25 term frequency / inverse document frequency weighting. |
| **Graph Database** | KùzuDB graph database with Cypher queries | Relational SQLite/PostgreSQL models + Python governance logic | **Divergence.** Entities exist relationally, but no dedicated graph database engine or Cypher query execution exists. |
| **Graph Traversal** | Multi-hop neighbor expansion along graph edges | Seed chunks returned directly from hybrid search without graph expansion | **Missing.** Graph traversal is documented but not executed on seed candidates. |
| **MCP Tool Names** | 15 dot-notated tools (`lore.get_context`, `lore.search`, etc.) | 4 underscore tools (`lore_search`, `lore_governed_query`, `lore_get_document`, `lore_ocr_extract`) | **Partial.** Missing 11 tools; naming convention uses underscores rather than dots. |
| **Embedding Models** | Mentions OpenAI / Ollama / Intel extensions | Local `SentenceTransformerEmbeddingAdapter` (`all-MiniLM-L6-v2`) only | **Focused.** Clean local zero-cost embedding, but documented OpenAI adapter is not implemented. |
| **Envelope Schema** | `lore.result/1` | `lore.result/2` (supported by schema validator) | **Enhanced.** Includes structured layers breakdown and telemetry timing. |

---

## 8. Recommended Next Steps Ordered by Impact

### Priority 1: MCP Tool Surface Alignment (High Impact, Low Effort)
- Register `lore.get_context` as an exact alias to `lore_governed_query` in `backend/mcp_server.py`.
- Support both dot notation (`lore.get_context`, `lore.search`) and underscore notation (`lore_search`, `lore_governed_query`) in `execute_tool`.
- Accept `file_path` as an alias for `query` or `document_title` matching IDE conventions.
- Register lightweight implementations for the most critical missing tools: `lore.check_compliance`, `lore.detect_conflicts`, `lore.get_history`, and `lore.trace`.

### Priority 2: Graph Adjacency Expansion on Seed Items (High Impact, Medium Effort)
- Implement a lightweight graph expansion step in `HybridRetrievalService.search()`:
  - When seed chunks are retrieved, expand them by querying related entities via relational foreign keys and lookup tables (`ConflictRecord`, `ScopedException`, `DocumentVersion`).
  - Traverse `SUPERSEDES` chains to ensure the current version replaces superseded chunks before reranking.
  - Tag expanded chunks with `traversal_edge: 'SUPERSEDES' | 'CONFLICTS_WITH'` to enrich context without requiring KùzuDB migration.

### Priority 3: Full-Text Search Upgrade (Medium Impact, Low Effort)
- Upgrade `apps/retrieval/services.py` lexical search from `text__icontains` to:
  - SQLite: SQLite FTS5 virtual table (`CREATE VIRTUAL TABLE chunk_fts USING fts5(...)`) for local dev.
  - PostgreSQL: `SearchVector` and `SearchQuery` (`GIN` index on `DocumentChunk.text`) with `SearchRank` in production.
  - This replaces naive substring matching with genuine BM25/TF-IDF lexical scoring.

### Priority 4: OpenAI & Ollama Embedding Adapters (Medium Impact, Low Effort)
- In `backend/apps/retrieval/embeddings.py`, implement `OpenAIEmbeddingAdapter` (using `text-embedding-3-small`, 1536d or 384d projection) and `OllamaEmbeddingAdapter` to match the configuration options declared in `settings.py`.
- Validate vector dimensions dynamically when initializing collections in Qdrant.

### Priority 5: Deduplication in Grounded Synthesis (Low Impact, Trivial Effort)
- In `apps/decisions/engine.py` (`_generate_deterministic_synthesis`), deduplicate paragraphs by document ID and page number so multiple chunks from the same page do not repeat identical excerpts in the final answer string.

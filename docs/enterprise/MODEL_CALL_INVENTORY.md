# LORE Enterprise — Model Call Inventory

This document provides a comprehensive, rigorous inventory of every point in the LORE Enterprise platform where an external inference, embedding, OCR, or generative model could be invoked, compared directly against the engine's built-in deterministic code alternatives.

## Executive Summary

LORE Enterprise implements a **Deterministic-First, Model-Minimal Architecture**. Models (LLMs, external inference APIs) are strictly prohibited from acting as the source of truth for governance decisions, permissions, temporal validity, authority ladder ranking, or evidence sufficiency.

```
                           +--------------------------------------+
                           |          Incoming Request            |
                           +--------------------------------------+
                                              |
                                              v
                           +--------------------------------------+
                           |   Execution Strategy Mode Filter     |
                           | (local_only / det_first / approved)  |
                           +--------------------------------------+
                                              |
                                              v
                           +--------------------------------------+
                           |      Deterministic Core Pipeline     |
                           |   - Normalization & SHA-256 Hashes   |
                           |   - Full-Text Lexical (BM25 / SQL)   |
                           |   - Local Dense Embedding (MiniLM)   |
                           |   - Bounded Relational Graph Traversal|
                           |   - 9-Layer Authoritative Precedence |
                           +--------------------------------------+
                                              |
                     +------------------------+------------------------+
                     |                                                 |
         [Non-Supported State]                               [Supported / Qualified]
         (denied / violation /                                         |
          insufficient / etc.)                                         v
                     |                                      [Generative Task Requested
                     v                                       & Explicitly Authorized?]
        +-------------------------+                                    |
        |  100% Deterministic     |                        +-----------+-----------+
        |  Directive & Answer     |                        |                       |
        |  (0 Tokens / $0.00)     |                     [No]                     [Yes]
        +-------------------------+                        |                       |
                                                           v                       v
                                              +-------------------------+ +---------------------+
                                              | Grounded Deterministic  | | Approved Remote LLM |
                                              | Extractive Synthesis    | | (Groq / OpenAI)     |
                                              | (0 Tokens / $0.00)      | | Monitored & Metered |
                                              +-------------------------+ +---------------------+
```

---

## Complete Component Inventory

| # | Pipeline Stage | Model-Assisted Path | Deterministic Code Path | Default Implementation | Local vs Remote | Tokens / Ingestion or Query | Latency (P50) | Estimated Cost / 1,000 Invocations | Deterministic Fallback Guaranteed? |
|---|----------------|---------------------|--------------------------|------------------------|-----------------|-----------------------------|---------------|------------------------------------|-----------------------------------|
| **1** | **Document Binary Parsing** | Multimodal Document Parsers / Cloud Document APIs | Native binary parsers: `pdfplumber`, `python-docx`, `openpyxl`, `zipfile_xml`, `utf-8` | Native deterministic parsers | Local | 0 tokens | ~1.2 ms / page | $0.00 | Yes (100% code) |
| **2** | **OCR & Text Extraction** | Cloud Vision APIs (Google Document AI / AWS Textract) | Optional local Tesseract OCR (`5.5.0`) with EXIF & OSD rotation + Lanczos upscaling | Dual Routing: Digital PDF text preserved; Tesseract only for scanned pages | Local | 0 tokens | 1.2 ms (digital) / 1,362 ms (scanned) | $0.00 | Yes (Digital stream preserved if OCR missing) |
| **3** | **Font Corruption Repair** | Generative LLM text rewriting | Regex & phonetic syllable reordering (`repair_visual_bengali_document`) | Deterministic Unicode normalization | Local | 0 tokens | 0.10 ms | $0.00 | Yes (Pure regex & Unicode substitution) |
| **4** | **Document Chunking** | LLM-based semantic chunking | Markdown header & token sliding window chunker (`RecursiveChunker`) | Deterministic structural chunking | Local | 0 tokens | 0.45 ms / doc | $0.00 | Yes (100% code) |
| **5** | **Document & Query Embeddings** | Remote Embedding APIs (OpenAI `text-embedding-3-small`, Cohere) | Local SentenceTransformers (`all-MiniLM-L6-v2`, 384 dimensions) | Local SentenceTransformers on CPU/GPU | Local | 0 remote tokens | 3.2 ms / query | $0.00 | Yes (`ALLOW_HASH_PROJECTION_FALLBACK` for test) |
| **6** | **Lexical Indexing & Search** | Neural sparse / lexical expanders | PostgreSQL Full-Text Search (`tsvector`, `tsquery`, GIN) / SQLite trigram | Relational SQL Full-Text Search | Local | 0 tokens | 1.8 ms | $0.00 | Yes (100% SQL) |
| **7** | **Vector Search & Storage** | Cloud managed vector databases (Pinecone / Weaviate Cloud) | Embedded/Self-hosted Qdrant Vector Database | Local/Containerized Qdrant Engine | Local | 0 tokens | 4.1 ms | $0.00 | Yes (Circuit breaker falls back to lexical) |
| **8** | **Graph Traversal Expansion** | Generative LLM Graph Extraction / GraphRAG Agents | Bounded Relational Adjacency Traversal (`KnowledgeRelationship` SQL) | Deterministic BFS traversal with depth budget | Local | 0 tokens | 1.5 ms | $0.00 | Yes (Strict depth & node bounds) |
| **9** | **Context Re-ranking** | Cross-encoder models (Cohere Rerank API, BGE Reranker) | Deterministic Token & Phrase Coverage + RRF Normalized Seed Score (`ContextReranker`) | Exact n-gram & token coverage scoring | Local | 0 tokens | 0.15 ms | $0.00 | Yes (Zero model calls) |
| **10** | **L7 Permission Layer** | LLM access evaluation | Cryptographic RBAC / ABAC matrix + tenant isolation | Deterministic SQL authorization filters | Local | 0 tokens | 0.08 ms | $0.00 | Yes (Fail-closed authorization) |
| **11** | **L1 Decision Intelligence** | LLM intent classifier | Deterministic statutory keyword regex & explicit decision catalog | Regex & decision type catalog | Local | 0 tokens | 0.05 ms | $0.00 | Yes (Fallback to `general_inquiry`) |
| **12** | **L5 Temporal Validity Layer** | LLM date reasoning | ISO-8601 point-in-time comparison (`effective_from`, `expires_at`, `as_of`) | Deterministic datetime arithmetic | Local | 0 tokens | 0.04 ms | $0.00 | Yes (Fail-closed expiry) |
| **13** | **L4 Scoped Exception Layer** | LLM exception adjudication | Time-bounded, scope-validated database exceptions registry | Relational exception lookup | Local | 0 tokens | 0.06 ms | $0.00 | Yes (Expired exceptions rejected) |
| **14** | **L6 Authority Ladder** | LLM contradiction resolution | Strict 7-rank authority ladder & version supersession logic | Deterministic integer hierarchy comparison | Local | 0 tokens | 0.09 ms | $0.00 | Yes (Equal-rank conflicts yield `conflicting`) |
| **15** | **L3 Evidence Sufficiency** | LLM completeness checking | Mandatory evidence requirement registry & checklist evaluator | Deterministic item-level validation | Local | 0 tokens | 0.07 ms | $0.00 | Yes (Missing checklist yields `insufficient`) |
| **16** | **L2 Answer-State Machine** | Generative outcome formulation | Invariant 9-verdict precedence ladder & canonical directive mapping | Deterministic state machine | Local | 0 tokens | 0.03 ms | $0.00 | Yes (Canonical state-directive matrix) |
| **17** | **L0 Observability & Traces** | Cloud APM / observability agents | Cryptographic trace generation (`trace-id`, `decision-id`, audit logging) | Relational `AuditEvent` & `DecisionRecord` | Local | 0 tokens | 0.40 ms | $0.00 | Yes (Synchronous SQLite/Postgres persistence) |
| **18** | **Answer Formulation (Non-supported States)** | LLM refusal generation | Deterministic refusal & guidance templates (denied, violation, etc.) | Deterministic state strings | Local | 0 tokens | 0.02 ms | $0.00 | Yes (LLM strictly prohibited) |
| **19** | **Answer Formulation (Factual / Routine)** | Cloud LLMs (Groq `gpt-oss-120B`, OpenAI `gpt-4o-mini`) | Grounded extractive passage synthesis with explicit provenance citations | Grounded Extractive Synthesizer | Local | 0 tokens | 0.02 ms | $0.00 | Yes (100% deterministic code) |
| **20** | **Answer Formulation (Complex Re-synthesis)** | Cloud LLMs (Groq `llama-3.3-70b`, `gpt-oss-120B`) with temperature 0.0 | Grounded extractive synthesis fallback | Optional remote provider (only when authorized) | Remote | ~800 prompt, ~250 completion | 850 ms | $0.59 / 1k queries | Yes (Clean fallback to extractive synthesis) |

---

## Detailed Architectural Analysis of Model Invocation Points

### 1. Document Extraction & OCR
- **Previous Risk:** Reliance on mandatory external cloud OCR APIs (e.g. Google Cloud Vision or Azure Computer Vision) leaks sensitive document content to third parties and incurs per-page billing.
- **LORE Implementation:** 
  - Standard digital documents (PDF, DOCX, CSV, XLSX, PPTX, TXT) are parsed 100% deterministically using Python native libraries with zero remote calls.
  - Tesseract OCR (`5.5.0`) is configured strictly as an **optional local provider**.
  - If Tesseract is not installed on the host system, digital extraction proceeds unimpeded. Pages with sparse digital text preserve the text stream, while pure scanned raster pages degrade gracefully with `provider_unavailable` status without crashing the ingestion job.
  - Zero external transmission occurs during document ingestion.

### 2. Semantic Dense Embeddings
- **Previous Risk:** Calling OpenAI `text-embedding-3-small` or cloud endpoints transmits proprietary documents outside tenant boundaries.
- **LORE Implementation:**
  - Standard embedding engine is the local `SentenceTransformerEmbeddingAdapter` using `all-MiniLM-L6-v2`.
  - Vectors are 384-dimensional dense float arrays generated locally on host CPU or GPU.
  - Query embeddings utilize the identical local model, guaranteeing complete dimensional and normalization compatibility (norm = 1.0 ± 0.05).
  - External network transmission: 0 bytes.

### 3. Governance Arbitration (Layers L7 through L0)
- **Previous Risk:** Allowing an LLM to evaluate authorization, permissions, or rule violations introduces prompt injection vulnerabilities and non-deterministic compliance failures.
- **LORE Implementation:**
  - All 9 governance layers execute pure Python and relational SQL code.
  - An LLM is NEVER called to determine permissions (L7), classify mandatory checklists (L1), evaluate expiration dates (L5), apply exceptions (L4), resolve contradictions (L6), verify evidence sufficiency (L3), or resolve state precedence (L2).
  - Terminal non-supported outcomes (`denied`, `violation`, `conflicting`, `insufficient`, `abstain`, `human_review`, `no_knowledge`) immediately terminate execution with deterministic refusal directives. Zero LLM tokens are consumed.

### 4. Answer Generation & Synthesis
- **Previous Risk:** Running an LLM on every routine factual lookup consumes massive token budgets and risks hallucination.
- **LORE Implementation:**
  - Routine factual lookups, policy citations, and statutory inquiries default to deterministic extractive synthesis. Sentences matching the authoritative passages are extracted, citations are bound to document coordinates (`document_id`, `version`, `page_number`, `heading_path`), and the canonical determination is formatted.
  - External models (Groq `gpt-oss-120B` / `llama-3.3-70b-versatile`) are invoked ONLY when:
    1. The execution mode is `deterministic_first` or `approved_remote`.
    2. A complex generative task is explicitly requested (`synthesis_mode='generative'`).
    3. The tenant policy explicitly authorizes remote processing (`allow_remote_llm = True`).
    4. A valid provider API key is present.
  - If any of these conditions are not satisfied, the engine falls back deterministically.

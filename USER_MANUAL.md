# LORE Enterprise — Comprehensive Operational Manual

> **Version:** 2.0.0-Enterprise  
> **Classification:** Enterprise Operational Standard  
> **Audience:** System Administrators, Compliance Officers, Legal Counsel, Platform Engineers, and AI Integration Architects

---

## Table of Contents

1. [Executive Operational Overview](#1-executive-operational-overview)
2. [Navigational Sitemap & Interface Tour](#2-navigational-sitemap--interface-tour)
3. [Workspace Management & Sovereign Isolation](#3-workspace-management--sovereign-isolation)
4. [Multi-Format Document Ingestion & 6-Stage Visual Settlement](#4-multi-format-document-ingestion--6-stage-visual-settlement)
5. [Review Queue & Quarantined Source Triage](#5-review-queue--quarantined-source-triage)
6. [Governed Search & Chat (RAG Studio)](#6-governed-search--chat-rag-studio)
7. [Knowledge Grid & RAPTOR v2.0 Visualizer](#7-knowledge-grid--raptor-v20-visualizer)
8. [Audit Ledger, Session Replay & Zero-Knowledge Verification](#8-audit-ledger-session-replay--zero-knowledge-verification)
9. [Enterprise Connectors](#9-enterprise-connectors)
10. [Compliance Packs & Policy Rulebooks](#10-compliance-packs--policy-rulebooks)
11. [Air-Gapped Offline Deployment & Database Topologies](#11-air-gapped-offline-deployment--database-topologies)
12. [Operational FAQ, Troubleshooting & Health Diagnostics](#12-operational-faq-troubleshooting--health-diagnostics)

---

## 1. Executive Operational Overview

### 1.1 The Operational Mandate
Modern enterprise organizations face severe legal and security liability when deploying Large Language Models (LLMs) and Autonomous Coding Agents across multi-thousand-page internal policies, engineering standards, and customer agreements. Standard Retrieval-Augmented Generation (RAG) suffers from five systemic vulnerabilities:
1. **Unchecked Policy Supersession:** LLMs ingest outdated 2021 guidelines alongside current 2026 mandates and arbitrarily blend them.
2. **Authority Blindness:** Informal Slack summaries or draft wiki pages are treated with identical weight to Board-approved policies.
3. **Hallucinated Citations:** Models invent nonexistent section numbers and file names when knowledge is missing.
4. **Silent Overrides:** Mandatory compliance prerequisites (such as executed Data Processing Addenda) are bypassed during code generation or architectural reviews.
5. **Multi-Tenant Leakage:** Draft, quarantined, or cross-departmental records leak into active model context windows.

**LORE Enterprise** acts as a deterministic, sovereign governor between retrieved enterprise documents and the AI context window. Lore guarantees that **untrusted knowledge never reaches model context** and **mathematical abstention** prevents fabricated approvals.

### 1.2 Target Personas & Access Models

| Persona | Primary Interface | Responsibilities | Key Capabilities |
|---|---|---|---|
| **Platform Administrator** | Web Console / Django Admin / CLI | Infrastructure configuration, storage allocation, tenant provisioning, backup drills | Full access to organizations, RBAC, connectors, and encryption keys |
| **Compliance Officer** | Web Console (Review Queue, Policy Packs) | Policy lifecycle management, exception approval, dispute adjudication | Authority ladder configuration, waiver issuing, compliance report signing |
| **Reviewer / Triage Analyst** | Web Console (Review Queue, OCR Studio) | Quarantined document inspection, OCR text correction, bounding box verification | Resolving OCR confidence alerts, approving quarantined drafts |
| **Auditor / Legal Counsel** | Web Console (Audit Ledger, Session Replay) | Forensic investigation, compliance validation, zero-knowledge proof verification | Query replay, SHA-256 Merkle root verification, tamper-evident exports |
| **Staff Engineer / AI Agent** | MCP Server (`mcp_server.py`) / IDEs | Code compliance verification, architectural design queries, automated CI/CD checks | Direct invocation of `lore.get_context`, `lore.search`, `lore.check_compliance` |

---

## 2. Navigational Sitemap & Interface Tour

The LORE Enterprise Web Console (`http://localhost:3000`) is built on the **Lavender + Sage** design system. The interface is organized into five functional groups in the sidebar:

```
┌────────────────────────────────────────────────────────────────────────┐
│  LORE Enterprise Web Console                                           │
├───────────────┬────────────────────────────────────────────────────────┤
│ WORKSPACE     │ Dashboard              (Overview, telemetry & metrics) │
│               │ Governed Chat          (RAG Studio & telemetry drawer) │
│               │ Knowledge Grid         (RAPTOR v2.0 graph visualizer)  │
├───────────────┼────────────────────────────────────────────────────────┤
│ KNOWLEDGE     │ Multi-Format Upload    (S1-S6 ingestion pipeline)      │
│               │ Document Registry      (Active documents & versions)   │
│               │ Review Queue           (Quarantined sources & triage)  │
├───────────────┼────────────────────────────────────────────────────────┤
│ SOURCES       │ Enterprise Connectors  (Confluence, Jira, GitHub, etc.)│
├───────────────┼────────────────────────────────────────────────────────┤
│ GOVERNANCE    │ Policy Rulebooks       (7-rank authority ladder)       │
│               │ Scoped Exceptions      (Time-bounded waivers)          │
│               │ Conflict Resolution    (Human adjudication interface)  │
│               │ Audit Ledger           (Immutable event trail)         │
├───────────────┼────────────────────────────────────────────────────────┤
│ PLATFORM      │ Identity & RBAC        (Users, roles, API keys)        │
│               │ Disaster Recovery      (Backups & ZKP verification)    │
│               │ Organization Settings  (Residency & tenant rules)      │
└───────────────┴────────────────────────────────────────────────────────┘
```

### 2.1 Theme & Accessibility Controls
- **Light / Dark Mode Toggle:** Located at the bottom of the navigation drawer. Persists state via `localStorage` and applies `.dark` tokens seamlessly.
- **Focus Indicators:** High-contrast focus rings ($\ge 3:1$ contrast ratio) enable full keyboard navigation via `Tab` and `Shift+Tab`.
- **Reduced Motion Support:** Respects OS-level accessibility flags (`prefers-reduced-motion: reduce`) by disabling non-essential transitions.

---

## 3. Workspace Management & Sovereign Isolation

A **Workspace** is a cryptographically isolated tenant partition in LORE. Chunks, vector embeddings, graph nodes, and policy rules in one workspace are completely inaccessible to queries targeting another workspace.

### 3.1 Creating and Configuring a Workspace
1. Navigate to **PLATFORM $\to$ Organization Settings**.
2. Click **Create New Workspace**.
3. Configure workspace metadata:
   - **Workspace Name:** Unique descriptor (e.g., `Engineering Core - Northstar`).
   - **Data Residency Region:** Restrict processing to specific geographies (e.g., `US-East`, `EU-Central`, `APAC-South`).
   - **Classification Floor:** Minimum classification level accepted (e.g., `Internal`, `Confidential`, `Restricted`).
   - **Default Token Budget:** Specify standard context cap (default: `800` tokens).
   - **Authority Enforcement Mode:** Select `Strict Fail-Closed` (recommended for production) or `Permissive Advisory`.

### 3.2 Role-Based Access Control (RBAC)
LORE enforces fine-grained permissions per workspace:
- **`owner`**: Can manage workspace lifecycle, delete documents, and alter residency configurations.
- **`admin`**: Can invite users, configure connectors, and issue scoped exceptions.
- **`editor` / `reviewer`**: Can upload documents, run ingestion jobs, and approve items in the Review Queue.
- **`viewer`**: Can perform governed searches, explore the Knowledge Grid, and inspect audit logs.

---

## 4. Multi-Format Document Ingestion & 6-Stage Visual Settlement

LORE ingests complex enterprise documentation (PDFs, multi-hundred-page textbooks, scanned agreements, DOCX, XLSX, Markdown) through a deterministic **6-Stage Visual Settlement Pipeline (S1–S6)**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                 6-STAGE VISUAL SETTLEMENT PIPELINE (S1-S6)                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  [S1] Multi-Format Parser & Layout Analysis                                 │
│       ├── Direct digital text extraction (<1.5 ms/page, 0.00% CER)          │
│       └── Bounding-box detection for headers, paragraphs, footers, & tables │
├─────────────────────────────────────────────────────────────────────────────┤
│  [S2] SLANet-Plus Table Structure Recognition                               │
│       ├── Grid line & cell coordinate detection                             │
│       └── Structural HTML / Markdown table reconstruction                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  [S3] Vision Fallback & Dual-Stream OCR                                     │
│       ├── 300 DPI Lanczos contrast booster & Otsu adaptive thresholding     │
│       ├── Orientation & Script Detection (OSD auto-rotation: 90°/180°/270°) │
│       └── SutonnyMJ / Bijoy legacy Bengali phonetic syllable repair         │
├─────────────────────────────────────────────────────────────────────────────┤
│  [S4] Heading-Aware Semantic Chunking                                       │
│       ├── Hierarchical parent-child document trees (H1 > H2 > H3 > Body)    │
│       └── Strict token boundaries (max 512 tokens, 64 token overlap)        │
├─────────────────────────────────────────────────────────────────────────────┤
│  [S5] Knowledge Graph & Entity Disambiguation                               │
│       ├── Named Entity Recognition (NER: Vendors, Regulations, Systems)     │
│       └── Typed edges: DEPENDS_ON, SUPERSEDES, DERIVED_FROM, CONTRADICTS    │
├─────────────────────────────────────────────────────────────────────────────┤
│  [S6] Zero-Knowledge Settlement & Merkle Commit                             │
│       ├── Cryptographic SHA-256 chunk hashing                               │
│       └── Root Merkle tree commitment written to immutable audit ledger     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Ingestion Execution via Console
1. Navigate to **KNOWLEDGE $\to$ Multi-Format Upload**.
2. Select target workspace and document authority ranking (e.g., `Rank 7: Approved Policy` or `Rank 3: Architectural Standard`).
3. Drag and drop target files or `.zip` archives.
4. Monitor stage progress cards in real time:
   - **Status Badge:** `Settled` (green) or `Quarantined` (amber).
   - **Telemetry:** Per-page extraction latency, OCR confidence score, and extracted chunk count.

---

## 5. Review Queue & Quarantined Source Triage

When an ingested document contains ambiguous layout, low OCR confidence, or detected policy contradictions, LORE automatically isolates it into the **Quarantine Review Queue**.

### 5.1 Quarantine Triggers
- **Low OCR Confidence:** Average extraction confidence drops below $80\%$.
- **Legacy Encoding Ambiguity:** Unmapped glyphs detected during Bijoy/SutonnyMJ font decoding.
- **Direct Contradiction:** Extracted MUST-rule conflicts with an existing equal-rank policy.
- **Missing Required Metadata:** Document lacks effective date, authoring department, or authority level.

### 5.2 Step-by-Step Triage Workflow
1. Navigate to **KNOWLEDGE $\to$ Review Queue**.
2. Select the quarantined item to open the **Triage Inspector**.
3. **Visual Inspection:**
   - The original page image is rendered on the left with interactive bounding boxes.
   - Extracted OCR text is displayed on the right with low-confidence tokens highlighted in amber.
4. **Correction:** Click any token or table cell to manually correct OCR transcriptions.
5. **Resolution Action:**
   - **Approve as Stable:** Promotes the document to `status = "stable"`. The chunks immediately become eligible for live retrieval.
   - **Reject & Purge:** Deletes extracted chunks and removes the document from the knowledge base.
   - **Request Re-scan:** Re-queues the document for high-resolution OCR with enhanced contrast filters.

---

## 6. Governed Search & Chat (RAG Studio)

The **Governed Chat Studio** (`http://localhost:3000/chat`) provides an interactive workbench for testing queries against the 10-stage retrieval read path and 9-layer governance engine.

### 6.1 Dual Token Budget Selection
In the chat interface, users and agents can toggle between two operational budgets:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Standard Mode (Default)          │  Deep Synthesis Mode                 │
├───────────────────────────────────┼──────────────────────────────────────┤
│  Token Cap: ≤ 800 tokens          │  Token Cap: up to 2,400 tokens       │
│  Passage Limit: ≤ 8 chunks        │  Passage Limit: ≤ 12 chunks          │
│  Severity Floor: Critical         │  Severity Floor: Low                 │
│  Target: IDE autocomplete,        │  Target: Multi-document book study,  │
│  fast compliance checks (<50ms)   │  statutory cross-policy comparisons  │
└───────────────────────────────────┴──────────────────────────────────────┘
```

### 6.2 Understanding the 9 Deterministic Answer States

Every response from LORE begins with a typed governance verdict and directive:

| Verdict | Directive | Operational Meaning | Action Required |
|---|---|---|---|
| `supported` | `proceed_and_cite` | All required evidence exists; zero policy violations found | Proceed with implementation or generation; cite provided chunks |
| `qualified` | `proceed` | Request is compliant under an active scoped exception (waiver) | Note the applied waiver and expiration date in audit notes |
| `insufficient` | `ask_user` | Query asks for approval, but mandatory prerequisite evidence is missing | Prompt user for required documentation (e.g. signed DPA) |
| `conflicting` | `ask_user` | Two equal-rank policies contain unreconciled opposing requirements | Escalate contradiction to human compliance officer |
| `violation` | `stop` | Request directly violates an active MUST/SHALL corporate rule | Halt operation immediately; display violated rule text |
| `denied` | `stop` | Request breaches an absolute security or statutory compliance floor | Hard rejection; logged in security audit log |
| `human_review` | `escalate` | Query involves high-liability operational decisions requiring human sign-off | Dispatch to human review queue with context envelope |
| `abstain` | `ask_user` | Query lies outside available authoritative documentation | Inform user that policy does not cover this domain |
| `no_knowledge` | `ask_user` | Zero matching chunks found within workspace permissions | Broaden search parameters or ingest relevant documentation |

### 6.3 Realtime Telemetry Drawer
Click the **Governance Telemetry** pill above the chat response to inspect the sub-millisecond execution trace:
- **L7 Filter:** Pruned chunk count.
- **L1 Classification:** Query domain and risk tier.
- **L5 Temporal Check:** Status of each chunk as of the evaluation timestamp.
- **L6 Ladder:** Authority rank of cited documents.
- **L3 Sufficiency:** Prerequisite checklists and pass/fail states.
- **Latency Breakdown:** Time spent in dense search, sparse search, RRF fusion, reranking, and governance verification.

---

## 7. Knowledge Grid & RAPTOR v2.0 Visualizer

The **Knowledge Grid** (`http://localhost:3000/graph`) provides an interactive, force-directed visualization of the organization's knowledge graph.

### 7.1 Visual Elements & Legend
- **Green Nodes:** Approved, stable documents and statutory compliance standards.
- **Blue Nodes:** Semantic chunks and extracted entities (systems, vendors, regulations).
- **Amber Edges (`DEPENDS_ON`):** Mandatory prerequisite relationships.
- **Purple Edges (`SUPERSEDES`):** Version lineage where a newer rule replaces an older one.
- **Red Edges (`CONTRADICTS`):** Identified opposing requirements between documents.

### 7.2 Graph-Guided Querying
1. Click any document node to highlight its direct 2-hop dependency tree.
2. Filter the view by **Authority Tier** (e.g., view only Rank 7 Board Policies).
3. Use the **Contradiction Filter** to isolate unresolved policy conflicts across departments.

---

## 8. Audit Ledger, Session Replay & Zero-Knowledge Verification

LORE Enterprise maintains an immutable, append-only audit trail of every query, retrieval, and decision.

### 8.1 Inspecting Decision Records
1. Navigate to **GOVERNANCE $\to$ Audit Ledger**.
2. Filter by `trace_id`, user email, workspace, or verdict.
3. Each record contains:
   - **Cryptographic Hash:** SHA-256 hash of the input query, retrieved chunk UUIDs, and emitted answer.
   - **Lineage:** Exact version and commit timestamp of every cited document.
   - **Stage Timings:** Exact millisecond execution profile.

### 8.2 Deterministic Session Replay
LORE enables forensic auditors to replay any historical query:
1. Open any `DecisionRecord` and click **Replay Session**.
2. LORE re-executes the query using the historical `as_of` timestamp and original configuration.
3. The replayed result is compared bit-for-bit against the recorded decision. A 100% hash match verifies that the governance engine operated deterministically without drift.

### 8.3 Zero-Knowledge Proof (ZKP) Commitments
Every settled batch of chunks generates a cryptographic **Merkle Tree Root**:
- Auditors can export the Merkle root to prove to external regulators that a specific policy was in effect on a specific date without disclosing confidential internal document text.

---

## 9. Enterprise Connectors

LORE synchronizes knowledge from enterprise repositories into sovereign workspaces through **Enterprise Connectors** (`frontend/src/components/EnterpriseConnectorsView.tsx`).

### 9.1 Supported Connectors & Protocols

| Connector | Supported Data Formats | Sync Cadence | Authentication Method |
|---|---|---|---|
| **Atlassian Confluence** | Spaces, Pages, Attachments (PDF/DOCX) | Real-time Webhooks / Hourly Polling | OAuth 2.0 / API Token |
| **Atlassian Jira** | Tickets, Epics, Sprint Compliance Checklists | Real-time Webhooks | OAuth 2.0 / API Token |
| **Microsoft SharePoint** | Document Libraries, Word, Excel, PowerPoint | Real-time Webhooks / 6-Hour Polling | Microsoft Entra ID (Azure AD) |
| **GitHub Enterprise** | Repositories, Markdown Docs, Pull Request Diffs | GitHub App Webhooks | Installation Token / SSH Key |
| **Google Workspace (Gmail/Drive)** | Emails, Drive Folders, Docs, Sheets | Daily Sync / Manual Trigger | Google Service Account (Domain-Wide Delegation) |
| **Enterprise Web Scraper** | Static & JavaScript-Rendered Internal Portals | Scheduled Cron (Daily / Weekly) | Basic Auth / Header Bearer Token |

### 9.2 Configuring a Connector
1. Navigate to **SOURCES $\to$ Enterprise Connectors**.
2. Select the target service (e.g., **Confluence**).
3. Enter connection parameters:
   - **Base URL:** `https://your-domain.atlassian.net/wiki`
   - **Target Space Keys:** Comma-separated spaces (e.g., `SEC,ENG,LEGAL`).
   - **Authority Rank:** Default authority assigned to ingested items (e.g., `Rank 4: Department Standard`).
4. Click **Test Connection**. Once verified, toggle **Enable Auto-Sync**.

---

## 10. Compliance Packs & Policy Rulebooks

### 10.1 The 7-Tier Authority Hierarchy
LORE resolves policy precedence through an immutable 7-rank authority ladder:

```
    [Rank 7] Statutory & Board Policies (GDPR, HIPAA, SOC 2, Articles of Inc.)
       ▲
    [Rank 6] Executive Mandates (CEO/CTO Directives, Global Security Policy)
       ▲
    [Rank 5] Enterprise Policies (Company-wide Handbooks, Data Governance)
       ▲
    [Rank 4] Department Standards (Engineering Architecture, HR Guidelines)
       ▲
    [Rank 3] Team Specifications (Service RFCs, System Design Documents)
       ▲
    [Rank 2] Project Guides (READMEs, Runbooks, Repository Guidelines)
       ▲
    [Rank 1] Informal Notes (Slack Summaries, Meeting Minutes, Scratchpads)
```
*Rule of Dominance:* A requirement in a higher-rank policy strictly overrides any contradictory text in a lower-rank policy.

### 10.2 Creating Scoped Exceptions (Waivers)
When a business unit requires a temporary deviation from an established policy:
1. Navigate to **GOVERNANCE $\to$ Scoped Exceptions**.
2. Click **Create Scoped Exception**.
3. Define waiver parameters:
   - **Rule Code:** The specific rule being waived (e.g., `SEC-RULE-402: Data Residency`).
   - **Target Scope:** Scope type (`department`, `project`, or `vendor`) and identifier.
   - **Effective Dates:** Strict `effective_from` and `effective_to` UTC timestamps.
   - **Approved By:** Approving compliance officer email and ticket reference.
4. When an AI agent queries the system within this scope and date window, LORE emits a `qualified` verdict instead of a `violation`, explicitly disclosing the waiver in the citation payload.

---

## 11. Air-Gapped Offline Deployment & Database Topologies

LORE Enterprise is engineered for air-gapped environments without external internet connectivity.

### 11.1 Zero-Dependency Local Setup (Default)
In default development and local air-gapped mode:
- **Database:** Local SQLite (`backend/db.sqlite3`) with WAL journal mode.
- **Vectors:** Local embedded Qdrant (`backend/qdrant_storage`).
- **Embeddings:** Local CPU-based SentenceTransformers (`all-MiniLM-L6-v2`).
- **Synthesis:** Deterministic rule synthesis or local Ollama instances (`http://127.0.0.1:11434`).
- **OCR:** Local Tesseract 5.4 binary with offline trained data.

### 11.2 Multi-Database Production Topology
In enterprise production deployments, LORE scales across dedicated clustering containers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   ENTERPRISE PRODUCTION TOPOLOGY                       │
├────────────────────────────────────────────────────────────────────────┤
│  Frontend (Next.js 16)        ──► Port 3000                            │
│  Backend Core (Django 4.2)    ──► Port 8000                            │
│  MCP Server (JSON-RPC / HTTP) ──► Port 8001 (/mcp)                     │
│  Relational Database          ──► PostgreSQL 16 Alpine (Port 5432)     │
│  Vector Store                 ──► Dedicated Qdrant Cluster (Port 6333) │
│  Task Queue / Caching         ──► Redis 7 Alpine (Port 6379)           │
│  Document Object Storage      ──► Private MinIO S3 (Port 9000/9001)    │
│  Asynchronous Workers         ──► Celery 5.3 Distributed Pool          │
└────────────────────────────────────────────────────────────────────────┘
```

### 11.3 Automated Disaster Recovery & Tamper Verification
LORE includes enterprise backup commands with cryptographic tamper detection:

```bash
cd backend

# Create an encrypted backup archive with SHA-256 checksums
python manage.py backup_enterprise --output-dir backups/production_backup

# Restore database records, vector indexes, and media fixtures
python manage.py restore_enterprise --backup-dir backups/production_backup --fix-mismatches
```

---

## 12. Operational FAQ, Troubleshooting & Health Diagnostics

### 12.1 Port Conflict Resolution
If port `8000`, `8001`, or `3000` is already bound by another process:
```powershell
# Identify process listening on port 8000
netstat -ano | findstr :8000

# Terminate offending PID
taskkill /F /PID <PID>

# Or execute turnkey cleanup
.\Stop_LORE.bat
```

### 12.2 Qdrant Storage Lock Warnings
If running concurrent benchmarks while the Django server is running locally, Qdrant embedded storage may report a lock warning. LORE automatically falls back to in-memory vector indexing and cached embeddings without interrupting test execution or user queries.

### 12.3 Diagnostic Health Endpoints

| Endpoint | Method | Expected HTTP Status | Diagnosis Checked |
|---|---|---|---|
| `/api/v1/health/` | `GET` | `200 OK` | Web service responsiveness |
| `/api/v1/health/ready/` | `GET` | `200 OK` | Database connectivity, vector engine readiness, OCR availability |
| `/api/v1/health/telemetry/` | `GET` | `200 OK` | Cumulative verdict distribution, latency percentiles, error rates |

---

## Manual Document Sign-Off

- **Lead Systems Architect:** Staff Retrieval & Governance Engineering
- **Security & Compliance Lead:** Enterprise Governance Team
- **Release Status:** `RELEASE_PERMITTED` (100% Gate Clearance)

# Lore

> *"Your lore, structured. Your AI, grounded."*  
> Built for the **International AI Builders Congress 2026** by **CloudCamp BD** · InfraSphere AI / Knowledge Grid track.

**Lore** is a governed knowledge platform and **Model Context Protocol (MCP)** suite for AI coding agents and enterprise engineering teams. Instead of dumping raw, unverified, or conflicting markdown and policy PDFs into an LLM's context window, Lore routes task-fit skills, evaluates deterministic governance rules, refuses to guess on contradictions, and records traceable decision receipts.

> **Repository structure:** `main` holds the unified platform documentation, IDE setup guides, and landing page. The two active product implementations live on separate branches:
> - [`solo`](https://github.com/starrynight-web/LORE/tree/solo) — **Lore Solo** (local-first skill & persona gateway for individual developers)
> - [`enterprise`](https://github.com/starrynight-web/LORE/tree/enterprise) — **LORE Enterprise** (airgap-capable, customer-deployed 9-layer governed knowledge grid)
> - *(Historical)* [`dev`](https://github.com/starrynight-web/LORE/tree/dev) — Earlier Go prototype (superseded by `solo` and `enterprise`)

---

## Platform Tiers at a Glance

| Tier | Branch / Status | Target Audience | Architecture & Storage | MCP Server Name | Key Capabilities |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Lore Solo** | [`solo`](https://github.com/starrynight-web/LORE/tree/solo) · **Built** | Individual developers & coding agents | Python 3.12 (`uvx`), local `.lore/` Markdown/OKF, OS persona library, Next.js setup dashboard, optional Graphify (`tree-sitter`) map | `lore-solo` | Persona-routed skills, draft-vs-approved governance, SkillSpector scan, decision receipts, auto-connect to IDEs |
| **Lore Team** | **Event Day Showcase** *(In Progress)* | Engineering teams & reviewers | Shared `.lore/` conventions + Git commit / PR comment adapter (`git_derived` drafts) + team activity feed | — | Collaborative conflict review, shared team conventions, PR-derived rule/decision drafts — **showcasing on Event Day at International AI Builders Congress by CloudCamp BD** |
| **LORE Enterprise** | [`enterprise`](https://github.com/starrynight-web/LORE/tree/enterprise) · **Built** | Enterprises & regulated engineering orgs | Django 4.2 + DRF, Next.js 16 + React 19, Qdrant Hybrid RRF + Bounded GraphRAG, PostgreSQL 16, Redis + Celery, MinIO | `lore-enterprise-mcp` | 9-layer fail-closed governance engine, 7-rank authority ladder, `as_of` temporal queries, dual-stream OCR + Bengali font repair, 11 MCP tools, audit lineage & RBAC |

---

## 1. Lore Solo (`solo` branch)

**Lore Solo** fixes skill overload for one developer's coding agent. You collect skills, file them under personas, connect Lore's MCP server to your IDE, and standing rules tell the agent to call Lore unprompted. Lore returns task-fit skill summaries and files to open—not your whole skill binder—and asks for a short receipt. Lore Solo's product promise is **better-guided work**, not guaranteed token savings.

### What It Provides
- **Project-as-Database (`.lore/`):** Personas and skills live as plain Markdown/YAML under `.lore/`, plus an OS-level shared persona library (`~/.local/share/lore`, macOS Application Support, or `%APPDATA%\Lore`).
- **Setup Dashboard (`lore-solo setup`):** Local Next.js + Django UI (`127.0.0.1:3000`) with an onboarding wizard, persona/skill manager, Graphify codebase map viewer, decision replay log, and token telemetry.
- **Graphify Codebase Map (`lore-solo map`):** Optional `tree-sitter` binary-wheel codebase map (`graphify-out/`) requiring zero C/C++ compilers.
- **Coding MCP Surface (`lore-solo`):** `get_context`, `get_skill`, `map_codebase`, `check_applied`, `log_decision` (plus 14 admin tools behind `lore-solo mcp --full`).
- **Container Support:** Optional Docker `mcp` and `full` targets with strict `/workspace` and `/library` bind mounts.

### Quick Start (`solo`)
```bash
uvx --managed-python --python 3.12 --no-build lore-solo==0.2.8 doctor
uvx --managed-python --python 3.12 --no-build lore-solo==0.2.8 install
lore-solo setup
lore-solo connect
```

See the [`solo` branch README](https://github.com/starrynight-web/LORE/blob/solo/README.md) for full CLI, Docker, and development instructions.

---

## 2. Lore Team *(Event Day Showcase)*

**Lore Team** bridges individual developer workflows and full enterprise governance. Designed around shared team conventions, a Git commit / PR comment adapter (`git_derived` rule and decision drafts), and a team activity feed for collaborative conflict resolution, the Team tier could not be finalized in time for this release.

> **Congress Day Preview:** The Team approach will be **showcased live on Event Day at the International AI Builders Congress 2026 by CloudCamp BD**.

---

## 3. LORE Enterprise (`enterprise` branch)

**LORE Enterprise** is a model-minimal, airgap-capable, customer-deployed **Governed Knowledge Grid & MCP Server** designed for mission-critical engineering teams and autonomous coding agents. Instead of blindly passing raw RAG chunks into an LLM, LORE executes a deterministic **9-layer governance pipeline** and fails closed whenever mandatory evidence is missing or policies conflict.

### What It Provides
- **9-Layer Deterministic Governance Engine:**
  - `L7` Pre-Model Permission Gate → `L1` Decision Intelligence → `L5` Temporal Validity (`as_of` point-in-time) → `L4` Scoped Exceptions → `L6` 7-Rank Authority & Conflict Ladder (refuses to guess on ties) → `L3` Evidence Sufficiency → `L2` 9-State Answer-State Precedence (`denied > violation > conflicting > insufficient > supported`) → Grounded Zero-Hallucination Synthesis → Canonical Contract Gate (`lore.result/2`) → `L0` Immutable Observability & Lineage (`DecisionRecord`, `AuditEvent`, `trace_id`).
- **Hybrid Retrieval & Bounded GraphRAG:** Dense embeddings (`all-MiniLM-L6-v2` in Qdrant) + lexical BM25/SQLite FTS5 merged via **Reciprocal Rank Fusion (RRF)**, plus bounded 2-hop graph traversal (`DEPENDS_ON`, `SUPERSEDES`, `DERIVED_FROM`, `CONTRADICTS`).
- **Dual-Stream Ingestion & OCR:** Direct digital PDF text extraction via `pdfplumber` (<1.5 ms/page) with automatic fallback to local Tesseract 5.4 OCR (300 DPI + OSD) and **legacy Bengali font reconstruction** (Bijoy / SutonnyMJ → exact Unicode).
- **11 Enterprise MCP Tools (`lore-enterprise-mcp`):** `lore.get_context`, `lore.search`, `lore.check_compliance`, `lore.get_authority_info`, `lore.query_as_of`, `lore.get_active_exceptions`, `lore.escalate_to_human`, `lore.bootstrap`, `lore.get_skill`, `lore.get_document`, `lore.ocr_extract`.
- **Next.js 16 Web Console:** Governed RAG Studio, Realtime OCR Studio, Ingestion Activity Pipeline, Human-in-the-Loop Review Queue, Audit & Decision Lineage Explorer, Multi-Tenant RBAC & Billing, plus SHA-256 tamper-evident Backup & Restore drills.

### Quick Start (`enterprise`)
```bash
git clone -b enterprise https://github.com/starrynight-web/LORE.git lore-enterprise
cd lore-enterprise
docker-compose up -d
```
*(Or run locally with Django `manage.py runserver` + Next.js `npm run dev` with automatic SQLite & embedded Qdrant fallbacks.)*

See the [`enterprise` branch README](https://github.com/starrynight-web/LORE/blob/enterprise/README.md) for full API, MCP, testing, and disaster recovery documentation.

---

## Connecting Your IDE

Both `lore-solo` and `lore-enterprise-mcp` speak standard MCP over stdio and support **Cursor**, **VS Code**, **Google Antigravity**, **Claude Desktop / Claude Code**, **OpenAI Codex**, **Devin**, **JetBrains**, and **Zed**.

> **Important:** Always register distinct MCP server names (`lore-solo` vs `lore-enterprise-mcp`) so IDE schema caches never collide. Do not use the deprecated `lore` key.

See [docs/ide/README.md](docs/ide/README.md) for client setup guides and compatibility status.

---

## Documentation

| Document | Contents |
| :--- | :--- |
| [docs/LORE_OVERVIEW.md](docs/LORE_OVERVIEW.md) | Platform overview, Solo vs Team vs Enterprise, and shared verdict vocabulary |
| [docs/LORE_ARCHITECTURE.md](docs/LORE_ARCHITECTURE.md) | Current implementation architectures (`solo` & `enterprise`) + historical v2.0 Congress spec |
| [docs/PROJECT_REQUIREMENTS.md](docs/PROJECT_REQUIREMENTS.md) | Functional & non-functional requirements with delivery status |
| [docs/PROJECT_CHARTER.md](docs/PROJECT_CHARTER.md) | Project scope, Congress milestones, and delivery status |
| [docs/ide/README.md](docs/ide/README.md) | IDE MCP setup, smoke test, and compatibility matrix |

## License

[MIT](LICENSE)

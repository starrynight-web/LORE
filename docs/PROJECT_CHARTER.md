# Lore — Project Charter

> "Your lore, structured. Your AI, grounded."

| Field | Value |
| --- | --- |
| Project | Lore — a Knowledge Grid engine for developers and enterprises |
| Competition | International AI Builders Congress 2026 · InfraSphere AI · **Knowledge Grid** track (Idea to Unicorn path) |
| Document | Project Charter |
| Version | 1.0 |
| Date | 2026-09-29 |
| Status | Draft for approval |
| Project Manager / Point of contact | Golam Morshed Eashan |
| Companion documents | `LORE_ARCHITECTURE.md` (v2.0), `PROJECT_REQUIREMENTS.md` (v1.0) |

---

## 1. Executive summary

Organizational knowledge — a developer's persona and skill files, a team's conventions, an enterprise's policies, Slack threads and PDFs — lives as flat, version-less, often stale text. AI systems cannot reason over it, cannot detect contradictions inside it, and cannot trace a decision back to it. Developers compensate by pasting context into every AI session; enterprises accept hallucinations from outdated policies and have no audit trail for AI-assisted decisions.

**Lore** turns that text into a **living, temporal knowledge graph** with **conflict detection**, **governance**, and **decision lineage**, and exposes it to any AI IDE or agent through the **Model Context Protocol (MCP)**. Instead of dumping thousands of tokens of context, Lore returns a governed result of at most 800 tokens with a clear verdict (`ok`, `conflict`, `abstain`, …), cited rule IDs, and a lineage record for every decision.

The project is built for the Knowledge Grid track ("Faster, grounded decisions — RAG + GraphRAG + governance") and follows a bottom-up wedge: **Personal Grid → Team Grid → Enterprise Grid**. Phase 1 must be complete and demonstrable for the **preliminary submission on Oct 31, 2026**; Phase 2 and Phase 3 are demonstrated as scoped proofs on **Congress Day, Dec 26, 2026**.

---

## 2. Background

### 2.1 The competition

- **Event:** International AI Builders Congress 2026 ([cloudcampbd.com/ai-builders-congress](https://cloudcampbd.com/ai-builders-congress)).
- **Track:** InfraSphere AI → Knowledge Grid — "Enterprise knowledge retrieval and reasoning". Specific ask: *faster, grounded decisions*. Details: *RAG + GraphRAG + governance*.
- **Example prompts from the brief** (each maps to a Lore capability):
  1. Real-time ingestion of Slack conversations and PDFs into a unified temporal knowledge graph.
  2. Conflict detection across versions of policy documents.
  3. Zero-Knowledge Proofs so sensitive data can be queried without exposing raw text.
  4. Federated RAG across international cloud regions with data sovereignty.
  5. Visual lineage tracing any AI response back to its source node.
- **Suggested data sources:** Common Crawl, SEC EDGAR, Enron Email Dataset, Azure Open Datasets, Hugging Face Hub.
- **Reference products named:** Palantir Gotham, Glean, Neo4j, Vectara, LlamaIndex.
- **Team rule:** 3–5 members plus **1 NRB (Non-Resident Bangladeshi) or international collaborator**.
- **Congress Day format:** about 14 teams per panel; 1 min transition + **3 min pitch** + 1 min scoring; at least 5 judges; scores normalized 0–100.

### 2.2 Judging rubric

| Criterion | Weight | How Lore scores |
| --- | --- | --- |
| Innovation | 20% | Conflict detection + temporal versions + governance verdicts + lineage in one graph, exposed through MCP — not offered together by any named reference product |
| Technical Execution | 20% | Real hybrid GraphRAG in Neo4j (the brief's named technology), Go engine, typed Jev decisions, working MCP in real IDEs, golden-dataset metrics |
| Business Model + Global Readiness | 20% | Open-core developer wedge → team SaaS → enterprise licences and compliance packs; multi-region design |
| Real-World Impact + Ethical AI Compliance | 20% | Audit trail for every AI decision, ABSTAIN-first governance, quarantine of untrusted extracts, residency audit, honest ZKP-lite scope |
| Scalability + NRB Collaboration | 10% | Federated two-region PoC, AWS-hosted demo, defined NRB role in governance and sovereignty design |
| Presentation | 10% | GUI lineage explorer and result card built to carry the 3-minute pitch |

### 2.3 The problem in detail

**Developers today:**

1. Write persona files (`backend.md`, `security.md`, `skills/`).
2. Paste or reference them manually in every AI session.
3. Hope the model reads and follows them.
4. Discover contradictions the hard way (bad code).
5. Update the files and repeat.

**Enterprises today:**

- **Hallucination from stale context** — the AI retrieves a 2025 policy that contradicts the 2026 version.
- **No conflict detection** — Slack, Confluence and a PDF disagree, and the AI cannot tell which is authoritative.
- **No audit trail** — no way to trace an AI decision to its exact source.
- **Data sovereignty blocks** — EU data cannot be queried by a US-hosted model under GDPR.
- **Context explosion** — feeding everything to a model exceeds limits and degrades quality.

**Why existing solutions fail:** they retrieve chunks rather than extract structured knowledge; they lack temporal versioning, conflict detection, graph reasoning over dependencies, and decision lineage; and they are not universally accessible from any AI IDE.

---

## 3. Purpose and business case

### 3.1 Purpose

Transform static knowledge into a governed, versioned knowledge graph that gives AI agents and people **precise, current, non-contradictory, traceable** context — replacing the "paste your context every session" workflow with automatic, auditable retrieval.

### 3.2 Value proposition

| Segment | Value |
| --- | --- |
| Individual developers | Automatic context in any AI IDE; target 85–95% fewer context tokens; higher rule compliance in generated code |
| Teams | Conflict-free shared conventions; decisions from Git history captured as knowledge |
| Enterprises | Sovereign, auditable retrieval; policy contradictions flagged before they cause harm |
| All | Auditable AI — every result traceable to sources, versions, and reviewers |

### 3.3 Business model (from the Lore business canvas)

- **Customer segments:** individual developers, startup teams, mid-market engineering orgs, regulated industries.
- **Channels:** GitHub / npm / pip, developer marketplaces, cloud marketplaces, direct and enterprise sales.
- **Revenue streams:** SaaS subscriptions (team), enterprise licences, compliance packs (SOC 2, HIPAA, OWASP), marketplace fees.
- **Key partners:** IDE vendors, MCP ecosystem, cloud providers, OSS communities, system integrators/consultancies.
- **Key resources:** graph engine IP, extraction pipelines, persona/rule pack library, community contributions.
- **Key activities:** graph engine development, MCP protocol maintenance, ingestion adapters, community/DevRel, enterprise sales.
- **Cost structure:** R&D engineering, cloud infrastructure, community/DevRel, enterprise sales.
- **Customer relationships:** OSS community, self-service SaaS, DevRel programs, enterprise customer success.

**Wedge strategy:** a developer is a team of one; an enterprise is a team at scale. One engine serves all three, enabling the bottom-up adoption path used by GitHub, Slack, and Figma.

### 3.4 Strategic fit

Lore is positioned as the first **graph-native MCP knowledge server** in a rapidly standardizing ecosystem, directly answering the track's "RAG + GraphRAG + governance" ask while remaining IDE-agnostic.

---

## 4. Vision, mission, and guiding principles

- **Vision:** every AI decision in software and in the enterprise is grounded in current, consistent, traceable knowledge.
- **Mission:** build the engine that structures knowledge, governs it, and delivers exactly the right slice of it to any AI agent — with receipts.

**Guiding principles** (full list in `LORE_ARCHITECTURE.md`):

1. Lore is the authority, not an LLM — deterministic checks and typed Jev decisions govern; LLMs only structure input (and, in Phase 3, write answers from a validated bundle).
2. Precision over recall — a false conflict is worse than a missed one; ABSTAIN when unsure.
3. Untrusted knowledge never reaches live context until promoted.
4. One result envelope (`lore.result/1`), three renderers (agent, GUI, CLI).
5. The graph features are mandatory: expansion, versioning, conflicts, lineage. Cut anything else first.

---

## 5. Objectives and success measures

All targets are measured on the Lore golden dataset (`testdata/golden/`) and the pre-seeded demo bundle unless stated.

| # | Objective | Measure | Target | Due |
| --- | --- | --- | --- | --- |
| O1 | Ship a working Personal Grid end to end | Ingest → promote → `get_context` in a real IDE → GUI lineage, on the first-demo scenario | Pass | Oct 31 |
| O2 | Deliver compact, governed context | Median / max tokens per `get_context` result | ≤ 400 / ≤ 800 | Oct 31 |
| O3 | Reduce context cost vs manual pasting | Tokens with Lore vs full persona pack pasted | ≥ 85% reduction | Oct 31 |
| O4 | Detect contradictions precisely | Conflict detection precision / recall on golden set | ≥ 0.90 / ≥ 0.70 | Dec 1 |
| O5 | Never serve superseded or unreviewed knowledge | Stale/draft/unverified items leaking into live context | 0 | Oct 31 |
| O6 | Abstain correctly | Correct `abstain` on "should abstain" golden cases | ≥ 0.80 | Dec 1 |
| O7 | Full traceability | Results with a reproducible Decision lineage record | 100% | Oct 31 |
| O8 | Responsive in the IDE | `get_context` p95 latency (warm, Jev cached / uncached) | ≤ 1.0 s / ≤ 2.0 s | Dec 1 |
| O9 | Improve compliance of AI-generated code | Rule pass rate on a scripted task set, with vs without Lore | Measurable uplift; target ≥ +25 points | Dec 1 |
| O10 | Demonstrate Team and Enterprise scope | Git-derived decisions slice + 3 Phase 3 PoCs visible in GUI | All 4 working | Dec 1 |
| O11 | Judge-proof demo | AWS stack + Docker fallback + recorded backup ready | All 3 ready | Dec 20 |
| O12 | Satisfy team composition rule | NRB/international collaborator confirmed with a defined role | Confirmed | Oct 31 |

---

## 6. Scope

### 6.1 In scope

**Phase 1 — Personal Grid (complete for Oct 31; hardened by Dec 1)**

- Background ingestion of Markdown and PDFs (text-layer; scanned via Tesseract OCR) through GUI and CLI.
- Source registry with authority tiers; normalize → extract (3B local LLM) → JSON Schema validation → draft/quarantine → promote.
- OKF v0.2 bundle as source of truth, with Lore frontmatter extensions.
- Neo4j temporal graph with versions, `SUPERSEDES`, dependencies, exemptions; vector + full-text indexes.
- Hybrid GraphRAG retrieval (keyword + vector → RRF → 2-hop expansion → temporal/authority filters → Jev applicability → ≤ 800 tokens).
- Governance: six conflict kinds, `Conflict` records, compliance checking, ABSTAIN, answer policy.
- Result presentation: `lore.result/1` envelope with verdict/directive vocabulary; agent text block, GUI result card, CLI output with exit codes.
- MCP server (read tools, controlled write tools, resources, prompts, server instructions) tested with VS Code and one agentic IDE; configs for all listed IDEs.
- React GUI (dashboard, ingest, review, graph, conflicts, timeline, decision log, lineage explorer, try-context, search, settings).
- cobra CLI (full command set; `--json`, `--plain`; exit codes).
- Decision lineage (PROV-style) and golden-dataset evaluation (`lore eval`).
- Observability-lite: OpenTelemetry traces, Prometheus metrics, JSON logs.

**Phase 2 — Team Grid (one demonstrable slice)**

- Git commit / PR comment adapter producing `git_derived` decision and rule drafts in the same graph.
- GUI activity list for git-derived decisions.

**Phase 3 — Enterprise Grid (three proofs of concept)**

- Ingestion generality: Enron emails (Slack stand-in) and policy PDFs through the same pipeline.
- Federated sovereignty: two-region residency tags, query router, `denied` verdict, residency audit panel.
- Privacy-preserving provenance: Merkle inclusion proofs shown with lineage (ZKP-lite, honestly scoped).

**Congress delivery**

- AWS-hosted pre-seeded demo, Docker Compose fallback, recorded backup video, 3-minute pitch, architecture one-pager.

### 6.2 Out of scope (for the Congress timeline)

- Model training or fine-tuning.
- 7B/8B or larger local models on either laptop; RAM upgrades.
- Answer prose generated by Lore in Phase 1–2 (the IDE's model writes answers).
- CRDT team sync, OAuth/SSO, RBAC, Stripe billing, Slack/Discord notifications (Phase 2 roadmap slides only).
- Confluence, SharePoint, Google Drive, live Slack API connectors; SAML/SCIM; air-gapped deployment; compliance packs (Phase 3 roadmap).
- Full zero-knowledge proofs over LLM output.
- Chroma/Weaviate/Pinecone, Redis, ELK, Unlimited-OCR on local hardware (evaluated and deferred — see architecture).
- Interactive full-screen TUI.
- Live extraction during the Congress pitch.

---

## 7. Deliverables

| # | Deliverable | Description | Due |
| --- | --- | --- | --- |
| D1 | Lore engine (Go) | Single binary: `lore serve`, `lore api`, `lore gui`, full CLI | Oct 31 (Phase 1) |
| D2 | Extract/OCR worker | Ollama 3B + Tesseract wrapper with `/extract`, `/ocr`, `/health` | Oct 12 |
| D3 | MCP server | Tools, resources, prompts, instructions; IDE config examples | Oct 31 |
| D4 | GUI | React app with all Phase 1 screens; lineage explorer | Oct 31 |
| D5 | Result envelope + renderers | `lore.result/1` JSON Schema; agent/GUI/CLI renderers | Oct 26 |
| D6 | OKF starter pack + demo bundle | Hand-authored conflicting rules, superseded versions, sources | Oct 17 |
| D7 | Golden dataset v1 + `lore eval` report | Metrics for O2–O8 | Oct 31 (v1), Dec 1 (v2) |
| D8 | Preliminary submission package | Demo video, architecture one-pager, repository link, business summary | Oct 31 |
| D9 | Team Grid slice | Git/PR adapter + GUI activity list | Nov 15 |
| D10 | Enterprise PoCs | Enron/PDF ingestion, two-region router, Merkle proofs in GUI | Dec 1 |
| D11 | Congress demo infrastructure | AWS stack, Docker Compose, recorded backup | Dec 20 |
| D12 | Pitch | 3-minute pitch deck + rehearsed script + Q&A sheet | Dec 22 |
| D13 | Documentation | README, IDE setup guides, architecture, charter, requirements | Rolling; final Dec 20 |

---

## 8. Milestones and schedule

| Week / window | Dates | Milestone | Exit criteria |
| --- | --- | --- | --- |
| W1 | Sep 29 – Oct 5 | **M1 Skeleton** | Go module, `lore init`, OKF parse/write, Neo4j schema, worker `/health`, CI green |
| W2 | Oct 6 – Oct 12 | **M2 Ingest & index** | Upload → source registry → normalize → extract → draft/quarantine → promote → graph; starter pack indexed |
| W3 | Oct 13 – Oct 19 | **M3 Retrieval (kill checkpoint 1)** | Hybrid GraphRAG returns correct rules for starter-pack tasks ≤ 800 tokens |
| W4 | Oct 20 – Oct 26 | **M4 Governance & presentation** | Conflicts + Jev + ABSTAIN; `lore.result/1`; MCP in VS Code; CLI renderers |
| W5 | Oct 27 – Oct 31 | **M5 Preliminary submission (kill checkpoint 2)** | GUI lineage + result card; golden v1 report; demo video; **submitted Oct 31** |
| — | Nov 1 – Nov 15 | **M6 Team slice + hardening** | Git/PR adapter; precision tuning; second IDE verified |
| — | Nov 16 – Dec 1 | **M7 Enterprise PoCs** | Enron/PDF, two-region router, Merkle proofs in GUI; golden v2 targets met |
| — | Dec 1 – Dec 20 | **M8 Freeze & deploy** | Feature freeze Dec 1; AWS stack; Docker fallback; recorded backup |
| — | Dec 20 – Dec 25 | **M9 Rehearsal** | 3-minute pitch rehearsed ≥ 10 times; Q&A sheet |
| — | Dec 26 | **Congress Day** | Live pitch and judging |

**Kill criteria (from the original brief):**

- If by **end of Week 3 (Oct 19)** graph retrieval is not working → drop to one IDE and two persona files; make one conflict detection and one lineage trace flawless.
- If by **end of Week 5 (Oct 31)** the full pipeline is not end to end → freeze features; spend the next week entirely on demo reliability and the metrics study.

---

## 9. Stakeholders and organization

### 9.1 Stakeholders

| Stakeholder | Interest | Influence |
| --- | --- | --- |
| Congress judges | Innovation, execution, impact, business viability, presentation | Decisive |
| Congress organizers / InfraSphere AI | Track fit, rules compliance, deadlines | High |
| Project Manager (Golam Morshed Eashan) | Delivery, scope, pitch | High |
| Build team | Feasible scope, clear requirements | High |
| NRB / international collaborator | Governance, sovereignty, global-readiness story | Medium–High |
| Technology partners (AWS; TypeSafe for Jev) | Showcase usage | Medium |
| Future users (developers, teams, compliance officers) | Usefulness, trust, privacy | Medium |

### 9.2 Roles

Team size: 3–5 builders + 1 NRB. One person may hold several roles.

| Role | Responsibilities |
| --- | --- |
| **Project Manager** | Scope, schedule, risks, submissions, stakeholder communication, pitch ownership |
| **Lead Engineer — Engine (Intel)** | Go engine, Neo4j, retrieval, governance, MCP, HTTP API, CLI, CI |
| **AI / Worker Engineer (Tecno)** | Ollama + OCR worker, extraction prompts and schema, Jev question design and thresholds, worker uptime |
| **Frontend Engineer** | React GUI, result card, lineage explorer, accessibility |
| **Data, QA & Demo Lead** | Starter pack, golden dataset, `lore eval`, demo bundle, recorded backup |
| **NRB / International Collaborator** | Governance and sovereignty design review, residency PoC input, global go-to-market perspective, pitch support |

### 9.3 RACI

R = Responsible, A = Accountable, C = Consulted, I = Informed.

| Activity | PM | Engine | AI/Worker | Frontend | Data/QA | NRB |
| --- | --- | --- | --- | --- | --- | --- |
| Scope & change control | A | C | C | C | C | C |
| Architecture decisions | C | A/R | R | C | C | C |
| Ingest, normalize, extract | I | A | R | I | C | I |
| Retrieval & governance | I | A/R | C | I | C | C |
| Jev integration & thresholds | I | C | A/R | I | C | I |
| Result envelope & renderers | I | A/R | I | R | C | I |
| MCP & IDE testing | I | A/R | I | I | R | I |
| GUI & lineage explorer | C | C | I | A/R | C | I |
| Golden dataset & eval | C | C | C | I | A/R | C |
| Sovereignty & provenance PoCs | C | A/R | I | R | C | C |
| AWS demo infrastructure | C | A/R | C | C | R | I |
| Submission & pitch | A/R | C | C | C | R | C |

---

## 10. Resources and budget

### 10.1 Hardware

| Device | Specs | Role |
| --- | --- | --- |
| Intel laptop | i5-12450H, 16 GB RAM, Intel UHD, CachyOS | Engine, Neo4j, GUI, CLI, IDE — primary build machine |
| Tecno MEGABOOK K15S | Ryzen 5 7430U, 16 GB RAM, integrated GPU | Worker: Ollama 3B Q4 + Tesseract only |

No hardware purchases or RAM upgrades are planned.

### 10.2 Software and accounts

GitHub (repository, Actions), TypeSafe Jev API key (`TYPESAFE_API_KEY`), Hugging Face (model downloads), AWS account (demo hosting), Docker. All other components are open source (Go, Neo4j Community, Ollama, Llama 3.2 / Qwen 2.5, Tesseract, React, Vite).

### 10.3 Budget estimate (indicative; confirm against current pricing and any partner credits)

| Item | Basis | Estimate |
| --- | --- | --- |
| Jev API | Reported ~US$0.042 per million input tokens; output free; ~500 input tokens per check | < US$5 for the whole project |
| AWS demo stack | One mid-size instance for Neo4j + Lore + GUI during Dec, plus a small second-region instance for the sovereignty PoC | ≈ US$50–150 (lower with credits) |
| Optional cloud LLM (fallback extraction, "Explain" button) | Pay-per-use, only if Tecno unavailable | ≤ US$20 |
| Domain / hosting extras | Optional | ≤ US$15 |
| **Total** | | **≈ US$75–190** |

---

## 11. Assumptions, constraints, and dependencies

### 11.1 Assumptions

- The Jev API remains available with early-access pricing through December 2026.
- The two laptops are available to the team for the whole build window.
- A 3B instruction model with a JSON Schema and quarantine is accurate enough for draft extraction when a human promotes results.
- MCP clients in target IDEs keep supporting stdio servers and structured tool results.
- Judges accept a pre-seeded demo with a recorded ingest segment.

### 11.2 Constraints

- **Time:** about 5 weeks to preliminary submission; about 13 weeks to Congress Day.
- **Hardware:** 16 GB RAM per laptop; no discrete GPU; no upgrades.
- **Stack mandate:** Go backend, Jev for typed reasoning, OKF as the knowledge format (manager direction, retained).
- **Team:** 3–5 builders + 1 NRB; mixed availability.
- **Pitch:** 3 minutes; the demo must not depend on the development LAN.

### 11.3 Dependencies

| Dependency | Used for | Fallback |
| --- | --- | --- |
| TypeSafe Jev API | Applicability, conflict, compliance, routing decisions | Deterministic checks + `abstain`; cached decisions for demo |
| Neo4j 5 Community | Graph, vector and full-text indexes | None planned (core) |
| Ollama + Llama 3.2 3B | Draft extraction | Qwen 2.5 3B; optional cloud LLM via same interface |
| Go MCP SDK | MCP server | Pin version; stdio transport |
| AWS | Judging-day hosting | Docker Compose on any single machine; recorded video |

---

## 12. Risks

| # | Risk | Level | Trigger / early warning | Mitigation | Owner |
| --- | --- | --- | --- | --- | --- |
| R1 | **Commodity build trap** — Lore looks like "another RAG wrapper" | Existential | Demo shows retrieval without conflicts/lineage | Graph features mandatory; pitch leads with conflict verdict + lineage | PM |
| R2 | **LLM extraction quality failure** | Existential | Inconsistent extraction by Week 2 | JSON Schema + quarantine + human promote; hand-authored starter pack for demo | AI/Worker |
| R3 | **Deadline slip** | Existential | Kill checkpoints missed | Weekly Friday E2E; kill criteria; cut scope before cutting graph features | PM |
| R4 | Conflict detection false positives | High | Precision < 0.90 on golden set | Deterministic kinds first; Jev confidence ≥ 0.70; ABSTAIN band; tune on golden set | AI/Worker |
| R5 | Live demo failure | High | Any rehearsal failure | Pre-seeded mode; AWS + Docker fallback; recorded backup; never live-extract | Data/QA |
| R6 | MCP protocol / IDE instability | High | IDE update breaks tools | Pin SDK; test two IDEs; CLI and GUI show the same result as fallback | Engine |
| R7 | GraphRAG misses critical rules | High | Golden recall drops | Hybrid keyword + vector seeds; component mapping; 2-hop expansion; eval on every change | Engine |
| R8 | Jev unavailable or rate-limited | Medium | API errors / latency spikes | Content-hash cache; deterministic fallback; `abstain` rather than guess | AI/Worker |
| R9 | Performance and latency | Medium | p95 > 2 s | Cache; batch Jev questions; limit candidates; Neo4j heap tuning | Engine |
| R10 | Token budget explosion | Medium | Expansion > 2,000 tokens pre-prune | Severity/modality-first pruning; `max_items` 8 | Engine |
| R11 | RAM pressure on 16 GB laptops | Medium | Swapping during dev | Worker on Tecno only; Neo4j heap 1 GB; `keep_alive=0` | Engine |
| R12 | Team skill gaps (Go, Neo4j, React) | Medium | Slow velocity in W1–W2 | Pairing; narrow package ownership; templates | PM |
| R13 | NRB collaborator not secured | Medium | Not confirmed by Oct 20 | Parallel outreach; defined, lightweight role | PM |
| R14 | Overclaiming ZKP/sovereignty | Medium (reputational) | Pitch language drift | Explicit "ZKP-lite / Merkle inclusion" wording reviewed by NRB | PM / NRB |
| R15 | OCR errors create false rules/conflicts | Medium | Low OCR confidence blocks | `ocr_min_confidence`; `extraction` conflict kind; exclude uncertain blocks from decisions | AI/Worker |

---

## 13. Governance and change control

### 13.1 Non-negotiable rules

1. **The graph features are mandatory** — expansion, versioning, conflicts, lineage. Cut anything else first.
2. **Friday demos, always** — working end to end every week, or the scope is wrong.
3. **Pre-seed the demo graph** — never live-extract during the showcase.
4. **Precision over recall** — in conflicts and retrieval, false positives are worse than misses.
5. **Recorded backup for every demo step.**

### 13.2 Decision-making

- Architecture decisions are recorded in `LORE_ARCHITECTURE.md` (revision history) by the Lead Engineer; the PM approves changes that affect scope, schedule, or the pitch.
- Requirements changes are recorded in `PROJECT_REQUIREMENTS.md` with a new version and requirement IDs; removed requirements are marked *Withdrawn*, never deleted.

### 13.3 Change control process

1. Proposer writes a short change note: what, why, affected requirements, effort, risk.
2. Lead Engineer assesses technical impact; PM assesses schedule/pitch impact.
3. Decision at the next stand-up or Friday review; recorded in the relevant document's revision history.
4. After **feature freeze (Dec 1)** only bug fixes and demo-reliability changes are accepted.

### 13.4 Quality gates

| Gate | When | Criteria |
| --- | --- | --- |
| G1 | Each PR | CI green; unit tests for touched packages; `lore.result/1` schema validation tests pass |
| G2 | Each Friday | End-to-end demo scenario passes on the current build |
| G3 | M5 (Oct 31) | Objectives O1, O2, O3, O5, O7, O12 met |
| G4 | M7 (Dec 1) | Objectives O4, O6, O8, O9, O10 met |
| G5 | M8 (Dec 20) | O11 met; three consecutive clean rehearsals on AWS |

---

## 14. Communication plan

| Channel | Frequency | Participants | Purpose |
| --- | --- | --- | --- |
| Stand-up (async text or 15-min call) | Daily | Build team | Progress, blockers |
| Friday E2E demo + review | Weekly | All incl. NRB (optional) | Demo, metrics, scope decisions |
| Milestone review | At M3, M5, M7, M8 | All | Gate decisions, kill criteria |
| Repository issues / PRs | Continuous | Build team | Work tracking, code review |
| Documentation | Continuous | Owners per doc | Architecture, requirements, charter updates |
| Organizer communication | As required | PM | Submissions, rules, logistics |

---

## 15. Ethics, privacy, and compliance

- **Untrusted content never governs:** extracted and unverified content is quarantined or badged until a human promotes it.
- **Honest uncertainty:** Lore returns `abstain` instead of guessing; confidence is shown in bands with exact values available.
- **Auditability:** every result writes a Decision lineage record with the rules used and excluded.
- **Data minimization:** traces and logs carry IDs, never raw document text; demo data uses public datasets (Enron, SEC EDGAR) and hand-authored rules.
- **Sovereignty:** residency tags and a router demonstrate that restricted data is not queried across regions; denials are logged.
- **Honest claims:** the privacy PoC is described as Merkle inclusion proofs (ZKP-lite), not full zero-knowledge proofs over model output.
- **Licensing:** only open-source components and models with licences that permit the demo use; attribution in the README.

---

## 16. Success criteria (project acceptance)

The project is successful when:

1. The preliminary submission is delivered on or before **Oct 31, 2026** with a working Personal Grid demo video and architecture summary.
2. Objectives O1–O12 are met at their gates.
3. On Congress Day the pitch runs in 3 minutes on the AWS stack (or fallback) without a failed step, showing: an IDE receiving a `conflict` verdict, the GUI result card, and the lineage explorer.
4. The NRB collaborator is confirmed and credited with a defined contribution.
5. Documentation (README, architecture, charter, requirements, IDE setup) is complete and consistent.

---

## 17. Approval

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Project Manager | Golam Morshed Eashan | | |
| Lead Engineer — Engine | | | |
| AI / Worker Engineer | | | |
| Frontend Engineer | | | |
| Data, QA & Demo Lead | | | |
| NRB / International Collaborator | | | |

---

## Revision history

| Version | Date | Author | Changes |
| --- | --- | --- | --- |
| 1.0 | 2026-09-29 | Lore team | Initial charter aligned with `LORE_ARCHITECTURE.md` v2.0 |

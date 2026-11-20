"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"

import { HashLink } from "@/components/hash-link"
import { IDES } from "@/components/ide-icons"
import { Reveal } from "@/components/reveal"
import { SiteFooter } from "@/components/site-footer"
import { SiteHeader } from "@/components/site-header"
import { scrollToHash } from "@/lib/scroll-to-hash"
import { cn } from "@/lib/utils"

const CODE_SNIPPETS = {
  solo: `# 1. Verify toolchain & install Lore Solo (Python 3.12 binary wheels)
uvx --managed-python --python 3.12 --no-build lore-solo==0.2.8 doctor
uvx --managed-python --python 3.12 --no-build lore-solo==0.2.8 install

# 2. Launch the local Bento setup dashboard & auto-connect your IDEs
lore-solo setup
lore-solo connect`,
  enterprise: `# Option A — Windows one-click launcher
# From the enterprise checkout:
Launch_LORE.bat
# or: start_lore.ps1

# Option B — Docker Compose (7-container governed grid)
git clone -b enterprise https://github.com/starrynight-web/LORE.git lore-enterprise
cd lore-enterprise && cp .env.example .env
docker-compose up -d

# Console at http://localhost:3000 · API at http://127.0.0.1:8000/api/v1/`,
} as const

type CodeTab = keyof typeof CODE_SNIPPETS

const PROOF = {
  solo: {
    title: "Persona-Routed Skill Summaries",
    desc: "Instead of flooding the context window with an entire skill binder, lore-solo returns task-fit summaries and files to open, then logs a receipt via check_applied and log_decision.",
    chips: ["lore-solo", ".lore/ OKF", "Graphify Map"],
    json: `{
  "schema": "lore.result/1",
  "server": "lore-solo",
  "decision_id": "dec-0042",
  "persona": "frontend-architect",
  "skills_served": ["bento-glass-tokens", "a11y-focus-ring"],
  "receipt_required": true
}`,
  },
  gov: {
    title: "9-Layer Fail-Closed Governance",
    desc: "Evaluates L7 Permissions, L5 Temporal Validity, L4 Scoped Exceptions, and L6 7-Rank Authority. Unresolved policy ties return conflicting → ask_user.",
    chips: ["lore-enterprise-mcp", "L7–L0 Pipeline", "7-Rank Ladder"],
    json: `{
  "schema": "lore.result/2",
  "verdict": "conflicting",
  "directive": "ask_user",
  "authority_tie": ["SEC-POL-04@v2", "VENDOR-ADDENDUM-D"],
  "escalated_to": "review-queue"
}`,
  },
  lineage: {
    title: "Immutable Decision & Audit Lineage",
    desc: "Every governed retrieval records cited chunk UUIDs, rule IDs, and stage latencies into DecisionRecord and AuditEvent with an end-to-end trace_id.",
    chips: ["trace_id", "DecisionRecord", "SHA-256 DR"],
    json: `{
  "trace_id": "trc_9f8a2c10e4",
  "verdict": "supported",
  "directive": "proceed_and_cite",
  "stage_latency_ms": { "L7": 0.4, "L5": 0.8, "L6": 1.1 },
  "audit_logged": true
}`,
  },
} as const

type ProofKey = keyof typeof PROOF

const WORKFLOW = [
  {
    num: "01 · COLLECT & STRUCTURE",
    title: (
      <>
        Markdown <code>.lore/</code> or Dual-Stream PDF/OCR
      </>
    ),
    desc: "Store personas and skills locally in Solo, or ingest policies via pdfplumber, Tesseract 5.4, and Bengali Bijoy/SutonnyMJ repair in Enterprise.",
    body: (
      <>
        <strong>Dual-Stream Preservation:</strong> Digital PDFs extract at &lt;1.5 ms/page with 0.00% CER.
        Legacy Bijoy/SutonnyMJ Bengali text is phonetically reconstructed into exact Unicode before indexing into
        Qdrant + FTS5.
      </>
    ),
    footer: "Drafts stay quarantined until human approval.",
  },
  {
    num: "02 · GOVERN & DETECT CONFLICTS",
    title: "Fail-Closed 9-Layer Pipeline",
    desc: "Evaluate permissions (L7), temporal validity (L5), scoped exceptions (L4), and the 7-rank authority ladder (L6). Ties trigger ask_user.",
    body: (
      <>
        <strong>Fail-closed evaluation:</strong> L7 permissions prune first, then L5 temporal windows, L4 scoped
        exceptions, and L6 authority ranks. Equal-rank conflicts never auto-resolve.
      </>
    ),
    footer: "Conflicting ties escalate to ask_user / review queue.",
  },
  {
    num: "03 · SERVE TYPED VERDICTS",
    title: "MCP Context + Immutable Receipts",
    desc: "Deliver ≤800-token cited results over stdio MCP and persist DecisionRecord + AuditEvent entries with end-to-end trace_id lineage.",
    body: (
      <>
        <strong>Typed MCP envelopes:</strong> Agents receive task-fit context with citations, then confirm with
        check_applied / log_decision so every serve leaves an auditable receipt.
      </>
    ),
    footer: "DecisionRecord + AuditEvent written with shared trace_id.",
  },
] as const

const TIERS = {
  solo: {
    ctaText: "Inspect solo Branch on GitHub →",
    ctaHref: "https://github.com/starrynight-web/LORE/tree/solo",
    cards: [
      {
        badge: "01",
        sage: true,
        title: "Project-as-Database (.lore/)",
        desc: "Plain Markdown & YAML skills under .lore/ plus an OS-wide shared persona library. Zero external database required.",
      },
      {
        badge: "02",
        sage: true,
        title: "Graphify Codebase Map",
        desc: "Optional tree-sitter binary-wheel codebase map (graphify-out/) with interactive viewer in the local setup dashboard.",
      },
      {
        badge: "03",
        sage: true,
        title: "5 Coding MCP Tools",
        desc: "get_context, get_skill, map_codebase, check_applied, and log_decision — focused on better-guided work.",
      },
    ],
  },
  team: {
    ctaText: "View Congress Day Charter →",
    ctaHref: "/congress/charter",
    cards: [
      {
        badge: "EVENT",
        sage: true,
        title: "Showcasing on Event Day",
        desc: "The Team tier is still in progress and will be showcased live at the International AI Builders Congress 2026 by CloudCamp BD.",
      },
      {
        badge: "GIT",
        sage: false,
        title: "Git & PR-Derived Drafts",
        desc: "Transforms commit histories and PR review comments into git_derived rule and decision drafts for team review.",
      },
      {
        badge: "SYNC",
        sage: false,
        title: "Shared Conflict Workflow",
        desc: "Team activity feed and collaborative conflict resolution bridging solo .lore/ bundles and enterprise governance.",
      },
    ],
  },
  enterprise: {
    ctaText: "Inspect enterprise Branch on GitHub →",
    ctaHref: "https://github.com/starrynight-web/LORE/tree/enterprise",
    cards: [
      {
        badge: "9L",
        sage: false,
        title: "9-Layer Governance Engine",
        desc: "L7 permissions, L5 as_of temporal queries, L4 scoped exceptions, L6 7-rank authority ladder, and L0 immutable audit lineage.",
      },
      {
        badge: "OCR",
        sage: true,
        title: "Dual-Stream OCR + Bengali Repair",
        desc: "Fast digital PDF preservation (<1.5 ms/page), Tesseract 5.4 fallback, and 100% exact Bijoy/SutonnyMJ Unicode repair.",
      },
      {
        badge: "BAT",
        sage: false,
        title: "Windows + Docker Install",
        desc: "One-click Launch_LORE.bat / start_lore.ps1 on Windows, plus 7-container Docker Compose for air-gapped enterprise deploys.",
      },
    ],
  },
} as const

type TierKey = keyof typeof TIERS

const BENCH = [
  { label: "Enterprise Acceptance Matrix", value: "100% PASS", width: "100%" },
  { label: "Legacy Bengali Unicode Reconstruction (Bijoy / SutonnyMJ)", value: "100% Exact", width: "100%" },
  { label: "Digital PDF Preservation Accuracy (pdfplumber, <1.5 ms/page)", value: "100% (0.00% CER)", width: "100%" },
  { label: "Bounded GraphRAG Traversal Budget (2–3 hops, cycle-safe)", value: "≤ 100 ms timeout", width: "88%" },
] as const

const GOVERNANCE_CARDS = [
  {
    badge: "L7–L0",
    sage: false,
    title: "9-Layer Governance",
    desc: "Pre-model permission pruning, temporal as_of queries, scoped waivers, and a 7-rank authority ladder that refuses to guess on ties.",
  },
  {
    badge: "RRF",
    sage: true,
    title: "Hybrid Qdrant + GraphRAG",
    desc: "Dense 384-dim embeddings + BM25/FTS5 merged via Reciprocal Rank Fusion, expanded over typed dependency & conflict edges.",
  },
  {
    badge: "SHA",
    sage: false,
    title: "Audit Lineage & DR",
    desc: "Immutable DecisionRecord & AuditEvent logs with trace_id links, Review Queue gating, and SHA-256 tamper-evident backup drills.",
  },
] as const

function highlightCode(raw: string) {
  return raw.split("\n").map((line, i) => {
    if (line.startsWith("#")) {
      return (
        <span key={i} className="c-comment">
          {line}
          {"\n"}
        </span>
      )
    }
    const parts = line.split(/(\buvx\b|\blore-solo\b|\bgit\b|\bcd\b|\bcp\b|\bdocker-compose\b|\bLaunch_LORE\.bat\b|\bstart_lore\.ps1\b)/g)
    return (
      <span key={i}>
        {parts.map((part, j) =>
          /^(uvx|lore-solo|git|cd|cp|docker-compose|Launch_LORE\.bat|start_lore\.ps1)$/.test(part) ? (
            <span key={j} className="c-cmd">
              {part}
            </span>
          ) : (
            <span key={j}>{part}</span>
          )
        )}
        {"\n"}
      </span>
    )
  })
}

function highlightJson(raw: string) {
  const html = raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"([^"]+)"(?=\s*:)/g, '<span class="c-key">"$1"</span>')
    .replace(/: "([^"]*)"/g, ': <span class="c-str">"$1"</span>')
    .replace(/\b(true|false)\b/g, '<span class="c-cmd">$1</span>')
    .replace(/: (\d+(?:\.\d+)?)/g, ': <span class="c-cmd">$1</span>')
  return <pre dangerouslySetInnerHTML={{ __html: html }} />
}

export function LandingPage() {
  const [bannerHidden, setBannerHidden] = useState(false)
  const [codeTab, setCodeTab] = useState<CodeTab>("solo")
  const [copied, setCopied] = useState(false)
  const [proofKey, setProofKey] = useState<ProofKey>("solo")
  const [step, setStep] = useState(0)
  const [tier, setTier] = useState<TierKey>("solo")

  const proof = PROOF[proofKey]
  const workflow = WORKFLOW[step]
  const tierData = TIERS[tier]
  const codeText = CODE_SNIPPETS[codeTab]

  const codeNodes = useMemo(() => highlightCode(codeText), [codeText])

  // Land on hash targets after route entry (sticky header + Next.js hash quirks)
  useEffect(() => {
    const hash = window.location.hash
    if (!hash) return
    const run = () => scrollToHash(hash, "smooth")
    const t = window.setTimeout(run, 50)
    return () => window.clearTimeout(t)
  }, [])

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(codeText)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* ignore */
    }
  }

  const banner = !bannerHidden ? (
    <div className="announcement-bar" id="congressBanner">
      <span>
        <strong>International AI Builders Congress 2026 · CloudCamp BD:</strong> Lore Team tier will be showcased
        live on Event Day.
      </span>
      <HashLink href="/#tiers" className="announcement-pill">
        See Tier Roadmap →
      </HashLink>
      <button
        type="button"
        className="close-banner"
        aria-label="Dismiss announcement"
        onClick={() => setBannerHidden(true)}
      >
        ×
      </button>
    </div>
  ) : null

  return (
    <>
      <SiteHeader banner={banner} />

      <main>
        <Reveal className="hero container" delay={40}>
          <h1>
            Your lore, structured.
            <br />
            Your AI, grounded.
          </h1>
          <p className="hero-sub">
            Governed knowledge &amp; Model Context Protocol (MCP) infrastructure for coding agents and enterprise
            teams. Return task-fit skills, deterministic verdicts, and traceable receipts — never blind RAG dumps.
          </p>
          <div className="hero-ctas">
            <HashLink href="/#quickstart" className="btn btn-lavender">
              Run Lore Solo →
            </HashLink>
            <HashLink href="/#tiers" className="btn btn-outline">
              Explore Enterprise
            </HashLink>
          </div>

          <div className="dot-matrix-stage" id="quickstart">
            <div className="code-window">
              <div className="code-tabs">
                <div className="tab-group" role="tablist" aria-label="Quick start tabs">
                  {(
                    [
                      ["solo", "Lore Solo (uvx)"],
                      ["enterprise", "LORE Enterprise (Docker / Windows)"],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className={cn("tab-btn", codeTab === id && "active")}
                      role="tab"
                      aria-selected={codeTab === id}
                      onClick={() => setCodeTab(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <button type="button" className="copy-btn" onClick={copyCode}>
                  {copied ? "Copied!" : "Copy"}
                </button>
              </div>
              <div className="code-body">
                <pre>{codeNodes}</pre>
              </div>
            </div>
          </div>
        </Reveal>

        <Reveal className="ecosystem-band container" delay={80}>
          <p className="ecosystem-sub">Works across 9+ AI coding harnesses with distinct server keys</p>
          <div className="ide-strip">
            {IDES.map((ide) => (
              <span key={ide.name} className="ide-chip">
                {ide.icon}
                {ide.name}
              </span>
            ))}
          </div>
        </Reveal>

        <Reveal className="dark-proof-band" id="proof" delay={60}>
          <div className="container">
            <div className="split-header">
              <h2>
                Built for <span className="mono">&lt;developers&gt;</span> who want proof, not promises
              </h2>
              <p>
                Lore never settles human contradictions on its own. Every MCP call returns a typed verdict, cited rule
                IDs, and an auditable decision record.
              </p>
            </div>

            <div className="proof-frame">
              <div className="proof-topbar">
                <div className="mac-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <div className="proof-tabs" role="tablist" aria-label="Proof examples">
                  {(
                    [
                      ["solo", "Solo Skill Routing"],
                      ["gov", "9-Layer Governance"],
                      ["lineage", "Audit Lineage"],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className={cn("proof-tab", proofKey === id && "active")}
                      onClick={() => setProofKey(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="proof-grid">
                <div className="proof-copy">
                  <h3>{proof.title}</h3>
                  <p>{proof.desc}</p>
                  <div className="proof-chips">
                    {proof.chips.map((chip) => (
                      <span key={chip} className="proof-chip">
                        {chip}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="proof-json">{highlightJson(proof.json)}</div>
              </div>
            </div>
          </div>
        </Reveal>

        <Reveal className="section container" id="workflow" delay={40}>
          <div className="section-head left">
            <h2>
              Add anything. Lore governs <span className="dotted-accent">every decision</span>
            </h2>
            <p>From local Markdown skills in Solo to multi-region PDF &amp; OCR ingestion in Enterprise.</p>
          </div>

          <div className="workflow-card">
            <div className="stepper-list" role="tablist" aria-label="Governance workflow steps">
              {WORKFLOW.map((item, idx) => (
                <button
                  key={item.num}
                  type="button"
                  className={cn("step-item", step === idx && "active")}
                  role="tab"
                  aria-selected={step === idx}
                  onClick={() => setStep(idx)}
                >
                  <span className="step-num">{item.num}</span>
                  <div className="step-title">{item.title}</div>
                  <p className="step-desc">{item.desc}</p>
                </button>
              ))}
            </div>

            <div className="workflow-canvas" role="tabpanel">
              <div className="canvas-bubble">
                <div className="canvas-kicker">Step {String(step + 1).padStart(2, "0")} detail</div>
                <div>{workflow.body}</div>
              </div>
              <div className="canvas-status">
                <span className="canvas-status-dot" aria-hidden="true" />
                Status: {workflow.footer}
              </div>
            </div>
          </div>
        </Reveal>

        <Reveal className="section container" id="tiers" delay={40}>
          <div className="section-head">
            <h2>Built for one developer, scaling to regulated enterprises</h2>
            <p>
              Solo and Enterprise are live on dedicated branches. Team will be showcased on Event Day at the
              International AI Builders Congress by CloudCamp BD.
            </p>
          </div>

          <div className="underline-tabs" role="tablist" aria-label="Platform tiers">
            {(
              [
                ["solo", "Lore Solo (solo branch)"],
                ["team", "Lore Team (Event Day Showcase)"],
                ["enterprise", "LORE Enterprise (enterprise branch)"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={cn("u-tab", tier === id && "active")}
                onClick={() => setTier(id)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="bento-grid-3">
            {tierData.cards.map((card) => (
              <div key={card.badge} className={cn("bento-card", card.sage && "sage-accent")}>
                <div className={cn("icon-box", card.sage && "lime")}>{card.badge}</div>
                <h3>{card.title}</h3>
                <p>{card.desc}</p>
              </div>
            ))}
          </div>

          <div className="tier-cta-wrap">
            <a
              href={tierData.ctaHref}
              className="btn btn-primary"
              target={tierData.ctaHref.startsWith("http") ? "_blank" : undefined}
              rel={tierData.ctaHref.startsWith("http") ? "noreferrer" : undefined}
            >
              {tierData.ctaText}
            </a>
          </div>
        </Reveal>

        <Reveal className="section container" id="benchmarks" delay={40}>
          <div className="section-head">
            <h2>Deterministic pipelines, verified end-to-end</h2>
            <p>Measured across LORE Enterprise&apos;s acceptance matrix, OCR benchmarks, and dual-stream ingestion suite.</p>
          </div>

          <div className="bench-list">
            {BENCH.map((row) => (
              <div key={row.label} className="bench-row">
                <div className="bench-meta">
                  <span>{row.label}</span>
                  <span className="mono">{row.value}</span>
                </div>
                <div className="bench-track">
                  <div className="bench-fill" style={{ width: row.width }} />
                </div>
              </div>
            ))}
          </div>
        </Reveal>

        <Reveal className="section container" id="governance" delay={40}>
          <div className="section-head">
            <h2>Built for enterprise. Designed for control.</h2>
            <p>Airgap-capable, customer-deployed knowledge grid with fail-closed contracts and tamper-evident recovery.</p>
          </div>

          <div className="bento-grid-3">
            {GOVERNANCE_CARDS.map((card) => (
              <div key={card.badge} className={cn("bento-card", card.sage && "sage-accent")}>
                <div className={cn("icon-box", card.sage && "lime")}>{card.badge}</div>
                <h3>{card.title}</h3>
                <p>{card.desc}</p>
              </div>
            ))}
          </div>
        </Reveal>

        <Reveal className="closing-cta container" delay={60}>
          <h2>
            Give your AI <span className="dotted-accent">structure</span> and proof
          </h2>
          <div className="hero-ctas" style={{ marginBottom: 0 }}>
            <HashLink href="/#quickstart" className="btn btn-lavender">
              Start with Lore Solo →
            </HashLink>
            <a
              href="https://github.com/starrynight-web/LORE/tree/enterprise"
              className="btn btn-primary"
              target="_blank"
              rel="noreferrer"
            >
              Deploy Enterprise →
            </a>
          </div>
        </Reveal>
      </main>

      <SiteFooter />
    </>
  )
}

import type { Metadata } from "next"
import Link from "next/link"

import { DocShell } from "@/components/doc-shell"

export const metadata: Metadata = {
  title: "Architecture Spec — LORE",
  description: "How Lore is structured across Solo and Enterprise implementations and the locked Congress blueprint.",
}

export default function ArchitecturePage() {
  return (
    <DocShell
      eyebrow="Documentation"
      title="Architecture Spec"
      description="Implementation split across specialized branches, plus the locked Knowledge Grid principles: OKF as contract, GraphRAG retrieval, fail-closed governance, and MCP exposure."
      githubHref="https://github.com/starrynight-web/LORE/blob/main/docs/LORE_ARCHITECTURE.md"
    >
      <div className="doc-meta">
        <span className="icon-box">v2.0</span>
        <span className="icon-box lime">GraphRAG</span>
        <span className="icon-box">Governance</span>
      </div>
      <h2>As built (2026-11-20)</h2>
      <ul>
        <li>
          <strong>Solo:</strong> Python 3.12 CLI/MCP, Next.js setup dashboard, .lore/ Markdown OKF, optional Graphify
          map
        </li>
        <li>
          <strong>Enterprise:</strong> Django 4.2 + Next.js 16, Qdrant hybrid RRF, bounded GraphRAG, Celery/Redis,
          MinIO, 9-layer engine, dual-stream OCR
        </li>
        <li>
          <strong>Team:</strong> deferred slice —{" "}
          <Link href="/congress/team-showcase">showcased on Congress Event Day</Link>
        </li>
      </ul>
      <h2>Locked principles</h2>
      <ul>
        <li>OKF is the curated source-of-truth contract — portable, not the only store</li>
        <li>GraphRAG path: keyword + vector seeds → graph expand → temporal/authority filter</li>
        <li>Deterministic stages handle dates, scopes, allow/deny, duplicates, and token budgets</li>
        <li>Governance never writes prose; unresolved ties escalate to humans</li>
      </ul>
      <p>
        Full spec:{" "}
        <a
          href="https://github.com/starrynight-web/LORE/blob/main/docs/LORE_ARCHITECTURE.md"
          target="_blank"
          rel="noreferrer"
        >
          docs/LORE_ARCHITECTURE.md
        </a>
      </p>
    </DocShell>
  )
}

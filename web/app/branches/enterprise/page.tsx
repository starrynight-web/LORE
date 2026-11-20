import type { Metadata } from "next"
import Link from "next/link"

import { DocShell } from "@/components/doc-shell"

export const metadata: Metadata = {
  title: "enterprise branch — LORE Enterprise",
  description:
    "LORE Enterprise: 9-layer governance, Qdrant + GraphRAG, dual-stream OCR, Windows .bat launcher, and Docker Compose.",
}

export default function EnterpriseBranchPage() {
  return (
    <DocShell
      eyebrow="Branches · enterprise"
      title="enterprise — LORE Enterprise"
      description="Customer-deployed knowledge grid with fail-closed 9-layer governance, hybrid retrieval, immutable audit lineage, and airgap-friendly installs."
      githubHref="https://github.com/starrynight-web/LORE/tree/enterprise"
    >
      <div className="doc-meta">
        <span className="icon-box lime">Phase 3</span>
        <span className="icon-box">9-Layer</span>
        <span className="icon-box lime">BAT + Docker</span>
      </div>
      <h2>Stack highlights</h2>
      <ul>
        <li>Django 4.2 + DRF API and Next.js console</li>
        <li>Qdrant hybrid RRF + bounded 2–3 hop GraphRAG</li>
        <li>Dual-stream PDF/OCR with Bengali Bijoy/SutonnyMJ Unicode repair</li>
        <li>
          MCP server key <code>lore-enterprise-mcp</code> (never collide with <code>lore-solo</code>)
        </li>
      </ul>
      <h2>Install paths</h2>
      <ul>
        <li>
          <strong>Windows:</strong> <code>Launch_LORE.bat</code> or <code>start_lore.ps1</code> from the enterprise
          checkout
        </li>
        <li>
          <strong>Docker:</strong> <code>docker-compose up -d</code> for the 7-container governed grid
        </li>
      </ul>
      <h2>Also see</h2>
      <ul>
        <li>
          <Link href="/docs/architecture">Architecture Spec</Link>
        </li>
        <li>
          <Link href="/docs/ide-mcp">IDE MCP Setup</Link>
        </li>
      </ul>
    </DocShell>
  )
}

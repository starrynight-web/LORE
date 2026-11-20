import type { Metadata } from "next"
import Link from "next/link"

import { DocShell } from "@/components/doc-shell"

export const metadata: Metadata = {
  title: "Platform Overview — LORE",
  description: "What Lore is: governed knowledge and MCP infrastructure for Solo, Team, and Enterprise.",
}

export default function OverviewPage() {
  return (
    <DocShell
      eyebrow="Documentation"
      title="Platform Overview"
      description="Lore is a governed knowledge platform and MCP suite. Agents ask what applies; Lore returns a typed verdict, directive, citations, and a decision record — never a blind RAG dump."
      githubHref="https://github.com/starrynight-web/LORE/blob/main/docs/LORE_OVERVIEW.md"
    >
      <div className="doc-meta">
        <span className="icon-box lime">MCP</span>
        <span className="icon-box">OKF</span>
        <span className="icon-box lime">Congress 2026</span>
      </div>
      <h2>Tagline</h2>
      <p>
        <em>Your lore, structured. Your AI, grounded.</em> Built for the International AI Builders Congress 2026 by
        CloudCamp BD · InfraSphere AI · Knowledge Grid track.
      </p>
      <h2>Three tiers</h2>
      <ul>
        <li>
          <strong>Lore Solo</strong> (<Link href="/branches/solo">solo</Link>) — personal .lore/ skills + coding MCP
        </li>
        <li>
          <strong>Lore Team</strong> — Event Day showcase for Git/PR-derived drafts and shared conflict workflow
        </li>
        <li>
          <strong>LORE Enterprise</strong> (<Link href="/branches/enterprise">enterprise</Link>) — 9-layer
          governance, hybrid retrieval, audit lineage
        </li>
      </ul>
      <h2>Core contract</h2>
      <ul>
        <li>Verdict: consistent, conflicting, uncertain, or denied</li>
        <li>Directive: what the agent must do next</li>
        <li>Cited rule / skill IDs with sources</li>
        <li>Traceable decision record — Lore never auto-settles human contradictions</li>
      </ul>
      <p>
        Full narrative:{" "}
        <a href="https://github.com/starrynight-web/LORE/blob/main/docs/LORE_OVERVIEW.md" target="_blank" rel="noreferrer">
          docs/LORE_OVERVIEW.md
        </a>
      </p>
    </DocShell>
  )
}

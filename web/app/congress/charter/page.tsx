import type { Metadata } from "next"
import Link from "next/link"

import { DocShell } from "@/components/doc-shell"

export const metadata: Metadata = {
  title: "Project Charter — LORE",
  description: "Congress 2026 project charter for Lore: Personal → Team → Enterprise Knowledge Grid wedge.",
}

export default function CharterPage() {
  return (
    <DocShell
      eyebrow="Congress 2026"
      title="Project Charter"
      description="Lore turns flat, stale organizational text into a temporal knowledge grid with conflict detection, governance, and decision lineage — exposed to AI IDEs through MCP."
      githubHref="https://github.com/starrynight-web/LORE/blob/main/docs/PROJECT_CHARTER.md"
    >
      <div className="doc-meta">
        <span className="icon-box lime">Knowledge Grid</span>
        <span className="icon-box">v1.0</span>
        <span className="icon-box lime">CloudCamp BD</span>
      </div>
      <h2>Delivery status</h2>
      <ul>
        <li>
          <strong>Phase 1 (Solo):</strong> built on the <Link href="/branches/solo">solo</Link> branch
        </li>
        <li>
          <strong>Phase 3 (Enterprise):</strong> built on the <Link href="/branches/enterprise">enterprise</Link>{" "}
          branch
        </li>
        <li>
          <strong>Phase 2 (Team):</strong> Event Day showcase — see{" "}
          <Link href="/congress/team-showcase">Team Event Showcase</Link>
        </li>
      </ul>
      <h2>Why Lore</h2>
      <p>
        Developers paste context into every AI session; enterprises accept hallucinations from outdated policies with
        no audit trail. Lore returns ≤800-token governed results with a clear verdict, cited rule IDs, and lineage for
        every decision.
      </p>
      <h2>Competition context</h2>
      <ul>
        <li>International AI Builders Congress 2026 · InfraSphere AI · Knowledge Grid track</li>
        <li>Brief: faster, grounded decisions via RAG + GraphRAG + governance</li>
        <li>Congress Day pitch format: short panel demos with normalized scoring</li>
      </ul>
      <p>
        Full charter:{" "}
        <a
          href="https://github.com/starrynight-web/LORE/blob/main/docs/PROJECT_CHARTER.md"
          target="_blank"
          rel="noreferrer"
        >
          docs/PROJECT_CHARTER.md
        </a>
      </p>
    </DocShell>
  )
}

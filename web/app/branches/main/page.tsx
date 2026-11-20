import type { Metadata } from "next"
import Link from "next/link"

import { DocShell } from "@/components/doc-shell"

export const metadata: Metadata = {
  title: "main branch — LORE",
  description: "Docs, landing site, and Congress deliverables on the LORE main branch.",
}

export default function MainBranchPage() {
  return (
    <DocShell
      eyebrow="Branches · main"
      title="main — Docs & Landing"
      description="The main branch hosts the public landing site, Congress documentation, and the shared product narrative for Solo and Enterprise."
      githubHref="https://github.com/starrynight-web/LORE/tree/main"
    >
      <div className="doc-meta">
        <span className="icon-box">main</span>
        <span className="icon-box lime">Docs</span>
        <span className="icon-box">Landing</span>
      </div>
      <h2>What lives here</h2>
      <ul>
        <li>This Next.js marketing site under <code>web/</code></li>
        <li>Platform overview, architecture, charter, and PRD under <code>docs/</code></li>
        <li>IDE MCP setup guides for Solo and Enterprise server keys</li>
      </ul>
      <h2>Related pages</h2>
      <ul>
        <li>
          <Link href="/docs/overview">Platform Overview</Link>
        </li>
        <li>
          <Link href="/docs/architecture">Architecture Spec</Link>
        </li>
        <li>
          <Link href="/congress/charter">Project Charter</Link>
        </li>
      </ul>
      <h2>Sibling branches</h2>
      <ul>
        <li>
          <Link href="/branches/solo">solo — Lore Solo</Link>
        </li>
        <li>
          <Link href="/branches/enterprise">enterprise — LORE Enterprise</Link>
        </li>
      </ul>
    </DocShell>
  )
}

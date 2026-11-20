import type { Metadata } from "next"
import Link from "next/link"

import { DocShell } from "@/components/doc-shell"

export const metadata: Metadata = {
  title: "solo branch — Lore Solo",
  description: "Lore Solo: local .lore/ OKF store, Graphify map, and lore-solo MCP for coding agents.",
}

export default function SoloBranchPage() {
  return (
    <DocShell
      eyebrow="Branches · solo"
      title="solo — Lore Solo"
      description="Personal Grid for one developer: Markdown skills under .lore/, optional Graphify codebase map, and a stdio MCP server that returns task-fit context with receipts."
      githubHref="https://github.com/starrynight-web/LORE/tree/solo"
    >
      <div className="doc-meta">
        <span className="icon-box lime">Phase 1</span>
        <span className="icon-box">lore-solo</span>
        <span className="icon-box lime">Built</span>
      </div>
      <h2>What you get</h2>
      <ul>
        <li>Python 3.12 CLI via <code>uvx</code> / <code>lore-solo</code></li>
        <li>Project-as-database: plain Markdown &amp; YAML under <code>.lore/</code></li>
        <li>Five coding MCP tools: get_context, get_skill, map_codebase, check_applied, log_decision</li>
        <li>Local Next.js Bento setup dashboard and IDE auto-connect</li>
      </ul>
      <h2>Quick start</h2>
      <p>
        Install with managed Python 3.12 wheels, then run <code>lore-solo setup</code> and{" "}
        <code>lore-solo connect</code>. Full IDE wiring is on the{" "}
        <Link href="/docs/ide-mcp">IDE MCP Setup</Link> page.
      </p>
      <h2>Also see</h2>
      <ul>
        <li>
          <Link href="/branches/enterprise">enterprise branch</Link>
        </li>
        <li>
          <Link href="/congress/team-showcase">Team Event Showcase</Link>
        </li>
      </ul>
    </DocShell>
  )
}

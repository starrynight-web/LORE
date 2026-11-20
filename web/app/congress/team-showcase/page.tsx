import type { Metadata } from "next"
import Link from "next/link"

import { DocShell } from "@/components/doc-shell"

export const metadata: Metadata = {
  title: "Team Event Showcase — LORE",
  description: "Lore Team tier showcase for International AI Builders Congress 2026 Event Day by CloudCamp BD.",
}

export default function TeamShowcasePage() {
  return (
    <DocShell
      eyebrow="Congress 2026"
      title="Team Event Showcase"
      description="The Team Grid slice bridges Solo .lore/ bundles and Enterprise governance. It was deferred from the current release and will be demonstrated live on Congress Event Day."
    >
      <div className="doc-meta">
        <span className="icon-box lime">Event Day</span>
        <span className="icon-box">Phase 2</span>
        <span className="icon-box lime">CloudCamp BD</span>
      </div>
      <h2>What will be showcased</h2>
      <ul>
        <li>Git &amp; PR-derived rule and decision drafts for team review</li>
        <li>Shared activity feed and collaborative conflict resolution</li>
        <li>Bridge between personal Solo skills and enterprise fail-closed pipelines</li>
      </ul>
      <h2>Status</h2>
      <p>
        Solo (<Link href="/branches/solo">solo</Link>) and Enterprise (
        <Link href="/branches/enterprise">enterprise</Link>) are live today. Team is the Congress Day narrative for
        collaborative governance — see the{" "}
        <Link href="/congress/charter">Project Charter</Link> delivery note and the landing{" "}
        <Link href="/#tiers">Solo · Team · Enterprise</Link> tabs.
      </p>
      <h2>Event</h2>
      <ul>
        <li>International AI Builders Congress 2026</li>
        <li>Organizer: CloudCamp BD</li>
        <li>Track: InfraSphere AI · Knowledge Grid</li>
      </ul>
    </DocShell>
  )
}

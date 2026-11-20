import type { Metadata } from "next"
import Link from "next/link"

import { DocShell } from "@/components/doc-shell"

export const metadata: Metadata = {
  title: "Requirements (PRD) — LORE",
  description: "Functional and non-functional requirements for Lore Solo, Team showcase, and Enterprise proofs.",
}

export default function RequirementsPage() {
  return (
    <DocShell
      eyebrow="Congress 2026"
      title="Requirements (PRD)"
      description="What Lore must do, how well it must do it, the interfaces it exposes, and how each requirement is accepted for Congress delivery."
      githubHref="https://github.com/starrynight-web/LORE/blob/main/docs/PROJECT_REQUIREMENTS.md"
    >
      <div className="doc-meta">
        <span className="icon-box">PRD v1.0</span>
        <span className="icon-box lime">MoSCoW</span>
        <span className="icon-box">P1 · P2 · P3</span>
      </div>
      <h2>Scope</h2>
      <ul>
        <li>
          <strong>P1 Personal Grid:</strong> Lore Solo on <Link href="/branches/solo">solo</Link> — Must requirements
          implemented
        </li>
        <li>
          <strong>P2 Team Grid slice:</strong> deferred to Event Day showcase
        </li>
        <li>
          <strong>P3 Enterprise proofs:</strong> governance, hybrid retrieval, OCR lineage on{" "}
          <Link href="/branches/enterprise">enterprise</Link>
        </li>
      </ul>
      <h2>Conventions</h2>
      <ul>
        <li>
          IDs: <code>FR-</code> functional, <code>NFR-</code> non-functional, <code>DR-</code> data,{" "}
          <code>IR-</code> interface
        </li>
        <li>Priority: Must / Should / Could / Won&apos;t for this timeline</li>
        <li>&quot;Shall&quot; = mandatory; &quot;should&quot; = recommended</li>
      </ul>
      <h2>Companion docs</h2>
      <ul>
        <li>
          <Link href="/congress/charter">Project Charter</Link>
        </li>
        <li>
          <Link href="/docs/architecture">Architecture Spec</Link>
        </li>
      </ul>
      <p>
        Full PRD:{" "}
        <a
          href="https://github.com/starrynight-web/LORE/blob/main/docs/PROJECT_REQUIREMENTS.md"
          target="_blank"
          rel="noreferrer"
        >
          docs/PROJECT_REQUIREMENTS.md
        </a>
      </p>
    </DocShell>
  )
}

import Link from "next/link"

import { Reveal } from "@/components/reveal"
import { SiteFooter } from "@/components/site-footer"
import { SiteHeader } from "@/components/site-header"

type DocShellProps = {
  eyebrow: string
  title: string
  description: string
  children: React.ReactNode
  githubHref?: string
}

export function DocShell({ eyebrow, title, description, children, githubHref }: DocShellProps) {
  return (
    <div className="doc-shell">
      <SiteHeader />
      <main className="doc-page">
        <div className="container">
          <Reveal as="div" className="doc-hero" delay={40}>
            <p className="doc-eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
            <p className="doc-lead">{description}</p>
            <div className="doc-hero-actions">
              <Link href="/" className="btn btn-outline">
                ← Back to landing
              </Link>
              {githubHref ? (
                <a href={githubHref} className="btn btn-lavender" target="_blank" rel="noreferrer">
                  View on GitHub →
                </a>
              ) : null}
            </div>
          </Reveal>
          <Reveal as="div" delay={120} className="doc-body-wrap">
            <article className="doc-body">{children}</article>
          </Reveal>
        </div>
      </main>
      <SiteFooter />
    </div>
  )
}

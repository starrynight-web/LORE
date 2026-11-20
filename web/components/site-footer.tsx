import Link from "next/link"

const FOOTER = {
  branches: [
    { href: "/branches/main", label: "main (Docs & Landing)" },
    { href: "/branches/solo", label: "solo (Lore Solo)" },
    { href: "/branches/enterprise", label: "enterprise (LORE Enterprise)" },
  ],
  documentation: [
    { href: "/enterprise/docs", label: "Enterprise Docs & YC Pitch Deck" },
    { href: "/docs/overview", label: "Platform Overview" },
    { href: "/docs/architecture", label: "Architecture Spec" },
    { href: "/docs/ide-mcp", label: "IDE MCP Setup" },
  ],
  congress: [
    { href: "/congress/charter", label: "Project Charter" },
    { href: "/congress/requirements", label: "Requirements (PRD)" },
    { href: "/congress/team-showcase", label: "Team Event Showcase" },
  ],
} as const

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="container">
        <div className="footer-grid">
          <div>
            <Link href="/" className="brand" style={{ marginBottom: 10 }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/web-app-manifest-192x192.png"
                alt=""
                width={32}
                height={32}
                className="brand-mark"
              />
              <span>LORE</span>
            </Link>
            <p style={{ margin: 0, maxWidth: 300, fontSize: "0.9rem", opacity: 0.85 }}>
              Your lore, structured. Your AI, grounded. Built for the International AI Builders Congress 2026 by
              CloudCamp BD.
            </p>
            <div className="footer-badges">
              <span className="footer-badge">MCP Native</span>
              <span className="footer-badge">Airgap Capable</span>
              <span className="footer-badge">MIT License</span>
            </div>
          </div>
          <div className="footer-col">
            <h4>Branches</h4>
            <ul>
              {FOOTER.branches.map((item) => (
                <li key={item.href}>
                  <Link href={item.href}>{item.label}</Link>
                </li>
              ))}
            </ul>
          </div>
          <div className="footer-col">
            <h4>Documentation</h4>
            <ul>
              {FOOTER.documentation.map((item) => (
                <li key={item.href}>
                  <Link href={item.href}>{item.label}</Link>
                </li>
              ))}
            </ul>
          </div>
          <div className="footer-col">
            <h4>Congress 2026</h4>
            <ul>
              {FOOTER.congress.map((item) => (
                <li key={item.href}>
                  <Link href={item.href}>{item.label}</Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          <a
            href="https://www.unleft.space/"
            className="footer-credit"
            target="_blank"
            rel="noreferrer"
            aria-label="Built by UNLEFT"
          >
            <span className="footer-credit-label">Built by</span>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/logos/unleft_logo.png"
              alt=""
              width={28}
              height={28}
              className="footer-credit-logo"
            />
            <span className="footer-credit-name">UNLEFT</span>
            <span className="footer-credit-arrow" aria-hidden="true">
              ↗
            </span>
          </a>
        </div>
      </div>
    </footer>
  )
}

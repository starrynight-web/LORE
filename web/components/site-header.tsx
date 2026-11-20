"use client"

import Link from "next/link"

import { HashLink } from "@/components/hash-link"
import { ThemeToggle } from "@/components/theme-toggle"

const NAV = [
  { href: "/#quickstart", label: "Quick Start" },
  { href: "/#proof", label: "MCP Proof" },
  { href: "/#workflow", label: "How It Works" },
  { href: "/#tiers", label: "Solo · Team · Enterprise" },
  { href: "/#governance", label: "Governance" },
] as const

export function SiteHeader({ banner }: { banner?: React.ReactNode } = {}) {
  return (
    <div className="top-wrap">
      {banner}
      <header className="nav-inner container">
        <Link href="/" className="brand" aria-label="LORE home">
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
        <nav className="nav-links" aria-label="Primary">
          {NAV.map((item) => (
            <HashLink key={item.href} href={item.href}>
              {item.label}
            </HashLink>
          ))}
        </nav>
        <div className="nav-actions">
          <ThemeToggle />
          <a
            href="https://github.com/starrynight-web/LORE"
            className="btn btn-outline"
            target="_blank"
            rel="noreferrer"
          >
            GitHub
          </a>
          <HashLink href="/#quickstart" className="btn btn-lavender">
            Get Started →
          </HashLink>
        </div>
      </header>
    </div>
  )
}

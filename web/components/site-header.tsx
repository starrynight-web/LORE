"use client"

import Link from "next/link"
import { MenuIcon, XIcon } from "lucide-react"
import { useEffect, useId, useState } from "react"

import { HashLink } from "@/components/hash-link"
import { ThemeToggle } from "@/components/theme-toggle"

const NAV = [
  { href: "/#quickstart", label: "Quick Start" },
  { href: "/#proof", label: "MCP Proof" },
  { href: "/#workflow", label: "How It Works" },
  { href: "/#tiers", label: "Solo · Team · Enterprise" },
  { href: "/enterprise/docs", label: "Enterprise Docs" },
] as const

export function SiteHeader({ banner }: { banner?: React.ReactNode } = {}) {
  const [open, setOpen] = useState(false)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 901px)")
    const onChange = () => {
      if (mq.matches) setOpen(false)
    }
    mq.addEventListener("change", onChange)
    return () => mq.removeEventListener("change", onChange)
  }, [])

  const closeMenu = () => setOpen(false)

  return (
    <div className="top-wrap">
      {banner}
      <header className="nav-inner container">
        <Link href="/" className="brand" aria-label="LORE home" onClick={closeMenu}>
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
            className="btn btn-outline nav-desktop-cta"
            target="_blank"
            rel="noreferrer"
          >
            GitHub
          </a>
          <HashLink href="/#quickstart" className="btn btn-lavender nav-desktop-cta">
            Get Started →
          </HashLink>
          <button
            type="button"
            className="icon-btn nav-menu-toggle"
            aria-expanded={open}
            aria-controls={menuId}
            aria-label={open ? "Close menu" : "Open menu"}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <XIcon size={18} aria-hidden="true" /> : <MenuIcon size={18} aria-hidden="true" />}
          </button>
        </div>
      </header>
      <div
        id={menuId}
        className={open ? "mobile-nav open" : "mobile-nav"}
        hidden={!open}
      >
        <nav className="mobile-nav-links" aria-label="Mobile">
          {NAV.map((item) => (
            <HashLink key={item.href} href={item.href} onClick={closeMenu}>
              {item.label}
            </HashLink>
          ))}
        </nav>
        <div className="mobile-nav-actions">
          <a
            href="https://github.com/starrynight-web/LORE"
            className="btn btn-outline"
            target="_blank"
            rel="noreferrer"
            onClick={closeMenu}
          >
            GitHub
          </a>
          <HashLink href="/#quickstart" className="btn btn-lavender" onClick={closeMenu}>
            Get Started →
          </HashLink>
        </div>
      </div>
    </div>
  )
}

"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useTheme } from "next-themes"
import { useEffect, useState, type ComponentType } from "react"
import {
  CableIcon,
  FolderTreeIcon,
  HistoryIcon,
  LayoutDashboardIcon,
  LibraryIcon,
  MoonIcon,
  SettingsIcon,
  SunIcon,
  UsersIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"

const navItems: {
  href: string
  title: string
  icon: ComponentType<{ className?: string }>
  tone: string
}[] = [
  { href: "/", title: "Dashboard", icon: LayoutDashboardIcon, tone: "lavender" },
  { href: "/connect", title: "Connect", icon: CableIcon, tone: "sky" },
  { href: "/personas", title: "Personas", icon: UsersIcon, tone: "peach" },
  { href: "/skills", title: "Skills", icon: LibraryIcon, tone: "sage" },
  { href: "/codebase", title: "Codebase", icon: FolderTreeIcon, tone: "mint" },
  { href: "/replay", title: "Decisions", icon: HistoryIcon, tone: "amber" },
  { href: "/settings", title: "Settings", icon: SettingsIcon, tone: "rose" },
]

const toneClass: Record<string, string> = {
  lavender: "bg-[rgba(165,155,243,0.28)] text-[#6b5fd4] dark:bg-[rgba(165,155,243,0.22)] dark:text-[#c4bcf8]",
  sage: "bg-[rgba(143,188,143,0.32)] text-[#3f7a4a] dark:bg-[rgba(143,188,143,0.22)] dark:text-[#a8d5a2]",
  peach: "bg-[rgba(255,176,140,0.32)] text-[#c45f2e] dark:bg-[rgba(255,176,140,0.2)] dark:text-[#ffb48c]",
  sky: "bg-[rgba(125,184,220,0.32)] text-[#2a7aa8] dark:bg-[rgba(125,184,220,0.2)] dark:text-[#8ecae8]",
  rose: "bg-[rgba(232,150,180,0.3)] text-[#b04572] dark:bg-[rgba(232,150,180,0.2)] dark:text-[#f0a8c4]",
  mint: "bg-[rgba(120,200,180,0.3)] text-[#2a8a72] dark:bg-[rgba(120,200,180,0.2)] dark:text-[#7ed4bc]",
  amber: "bg-[rgba(240,190,110,0.34)] text-[#a86b12] dark:bg-[rgba(240,190,110,0.2)] dark:text-[#f0c878]",
}

function isCurrent(href: string, pathname: string) {
  if (href === "/") return pathname === "/"
  return pathname === href || pathname.startsWith(`${href}/`)
}

export function SiteHeader() {
  const pathname = usePathname()
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const isDark = mounted && resolvedTheme === "dark"

  return (
    <header className="mb-3 flex items-center justify-between gap-2 md:hidden">
      <Link
        href="/"
        aria-label="Lore home"
        className="grid size-10 shrink-0 place-items-center rounded-[10px] bg-gradient-to-br from-[#7c6fd6] to-[#5f52c4] text-sm font-bold text-white shadow-[0_4px_12px_rgba(95,82,196,0.32)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#5f52c4] focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-[#c4bcf8] dark:focus-visible:ring-offset-[#1d1f28]"
      >
        L
      </Link>

      <nav aria-label="Mobile navigation" className="flex flex-1 flex-wrap items-center justify-center gap-1.5">
        {navItems.map((item) => {
          const active = isCurrent(item.href, pathname)
          const Icon = item.icon
          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.title}
              aria-label={item.title}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex size-9 items-center justify-center rounded-[10px] transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#5f52c4] focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-[#c4bcf8] dark:focus-visible:ring-offset-[#1d1f28]",
                active
                  ? "bg-[#5f52c4] text-white shadow-[0_6px_16px_rgba(95,82,196,0.32)]"
                  : toneClass[item.tone]
              )}
            >
              <Icon className="size-4" />
            </Link>
          )
        })}
      </nav>

      <button
        type="button"
        onClick={() => setTheme(isDark ? "light" : "dark")}
        title={isDark ? "Switch to light theme" : "Switch to dark theme"}
        aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
        className="flex size-9 shrink-0 items-center justify-center rounded-full bg-white/75 text-foreground shadow-[0_2px_8px_rgba(0,0,0,0.03)] transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--lore-lavender)] dark:bg-white/8 dark:hover:bg-white/16"
      >
        {isDark ? <SunIcon className="size-4" /> : <MoonIcon className="size-4" />}
      </button>
    </header>
  )
}

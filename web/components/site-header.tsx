"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useTheme } from "next-themes"
import { useEffect, useState } from "react"
import {
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

const navItems = [
  { href: "/", title: "Dashboard", icon: LayoutDashboardIcon },
  { href: "/personas", title: "Personas", icon: UsersIcon },
  { href: "/skills", title: "Skills", icon: LibraryIcon },
  { href: "/codebase", title: "Codebase", icon: FolderTreeIcon },
  { href: "/replay", title: "Decisions", icon: HistoryIcon },
  { href: "/settings", title: "Settings", icon: SettingsIcon },
]

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
        className="flex size-9 shrink-0 items-center justify-center rounded-[10px] text-foreground transition-opacity hover:opacity-80"
      >
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 3a9 9 0 0 0 0 18" />
          <path d="M12 7a5 5 0 0 0 0 10" />
        </svg>
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
                "flex size-9 items-center justify-center rounded-full transition-all duration-150",
                active
                  ? "bg-[#1c1d21] text-white shadow-[0_6px_16px_rgba(0,0,0,0.14)] dark:bg-[#f3f4f8] dark:text-[#14151a]"
                  : "bg-white/75 text-muted-foreground shadow-[0_2px_8px_rgba(0,0,0,0.03)] hover:bg-white hover:text-foreground dark:bg-white/8 dark:hover:bg-white/16"
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
        title={isDark ? "Switch to light mode" : "Switch to dark mode"}
        aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
        className="flex size-9 shrink-0 items-center justify-center rounded-full bg-white/75 text-foreground shadow-[0_2px_8px_rgba(0,0,0,0.03)] transition-colors hover:bg-white dark:bg-white/8 dark:hover:bg-white/16"
      >
        {isDark ? <SunIcon className="size-4" /> : <MoonIcon className="size-4" />}
      </button>
    </header>
  )
}

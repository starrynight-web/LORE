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
  SearchIcon,
  SettingsIcon,
  SunIcon,
  UsersIcon,
} from "lucide-react"
import { toast } from "sonner"

import { cn } from "@/lib/utils"

type IconTone = "lavender" | "sage" | "peach" | "sky" | "rose" | "mint" | "amber"

type NavItem = {
  href: string
  title: string
  icon: ComponentType<{ className?: string }>
  tone: IconTone
}

const primary: NavItem[] = [
  { href: "/", title: "Workspace Overview", icon: LayoutDashboardIcon, tone: "lavender" },
  { href: "/connect", title: "Connect & MCP", icon: CableIcon, tone: "sky" },
]

const library: NavItem[] = [
  { href: "/skills", title: "Skills Library", icon: LibraryIcon, tone: "sage" },
  { href: "/personas", title: "Personas", icon: UsersIcon, tone: "peach" },
]

const project: NavItem[] = [
  { href: "/codebase", title: "Codebase", icon: FolderTreeIcon, tone: "mint" },
  { href: "/replay", title: "Decisions", icon: HistoryIcon, tone: "amber" },
]

const toneClass: Record<IconTone, string> = {
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

function NavIcon({
  icon: Icon,
  tone,
  active,
  size = "sm",
}: {
  icon: ComponentType<{ className?: string }>
  tone: IconTone
  active?: boolean
  size?: "sm" | "md"
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "grid shrink-0 place-items-center rounded-[8px] transition-colors",
        size === "md" ? "size-[30px] rounded-[9px]" : "size-7",
        active ? "bg-white/24 text-white" : toneClass[tone]
      )}
    >
      <Icon className={size === "md" ? "size-[15px]" : "size-3.5"} />
    </span>
  )
}

function PrimaryLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-[12.5px] font-semibold transition-all duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#5f52c4] focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-[#c4bcf8] dark:focus-visible:ring-offset-[#1d1f28]",
        active
          ? "bg-[#5f52c4] text-white shadow-[0_6px_16px_rgba(95,82,196,0.32)]"
          : "text-[#2e323a] hover:bg-white/55 hover:text-[#141517] dark:text-[#d8dae3] dark:hover:bg-white/8 dark:hover:text-[#f3f4f8]"
      )}
    >
      <NavIcon icon={item.icon} tone={item.tone} active={active} size="md" />
      <span className="min-w-0 truncate">{item.title}</span>
    </Link>
  )
}

function SubLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-1.5 text-left text-xs font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#5f52c4] focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-[#c4bcf8] dark:focus-visible:ring-offset-[#1d1f28]",
        active
          ? "bg-white/70 font-semibold text-[#141517] dark:bg-white/12 dark:text-[#f3f4f8]"
          : "text-[#2e323a] hover:bg-white/50 hover:text-[#141517] dark:text-[#d8dae3] dark:hover:bg-white/8 dark:hover:text-[#f3f4f8]"
      )}
    >
      <NavIcon icon={item.icon} tone={item.tone} />
      <span className="min-w-0 truncate">{item.title}</span>
    </Link>
  )
}

function NavGroup({
  label,
  items,
  pathname,
}: {
  label: string
  items: NavItem[]
  pathname: string
}) {
  const headingId = `nav-group-${label.toLowerCase().replace(/\s+/g, "-")}`
  return (
    <div className="mx-1 mb-3" role="group" aria-labelledby={headingId}>
      <div
        id={headingId}
        className="px-2.5 py-1.5 text-[10px] font-bold tracking-[0.08em] text-[#5a5e68] uppercase dark:text-[#9aa0b0]"
      >
        {label}
      </div>
      <div className="flex flex-col gap-0.5">
        {items.map((item) => (
          <SubLink key={item.href} item={item} active={isCurrent(item.href, pathname)} />
        ))}
      </div>
    </div>
  )
}

export function AppSidebar() {
  const pathname = usePathname()
  const settingsCurrent = isCurrent("/settings", pathname)
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const isDark = mounted && resolvedTheme === "dark"

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault()
        toast.message("Search & commands", {
          description: "Jump to Skills, Personas, or Settings from here soon.",
        })
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const openSearch = () => {
    toast.message("Search & commands", {
      description: "Jump to Skills, Personas, or Settings from here soon.",
    })
  }

  return (
    <aside
      aria-label="Workspace"
      className="sticky top-0 z-20 hidden h-screen w-[268px] shrink-0 flex-col overflow-y-auto border-r border-[rgba(20,22,30,0.06)] px-3 py-3.5 md:flex dark:border-white/7"
      style={{ background: "var(--lore-sidebar)" }}
    >
      <Link
        href="/"
        aria-label="Lore Solo home"
        className="mb-3 mx-1 flex items-center gap-2.5 rounded-xl px-2 py-1.5 transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#5f52c4] focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-[#c4bcf8] dark:focus-visible:ring-offset-[#1d1f28]"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/web-app-manifest-192x192.png"
          alt=""
          width={36}
          height={36}
          aria-hidden="true"
          className="size-9 shrink-0 rounded-[10px] shadow-[0_4px_12px_rgba(95,82,196,0.32)]"
        />
        <span className="truncate text-[13px] font-bold tracking-[-0.01em] text-[#18191d] dark:text-[#f3f4f8]">
          Lore Solo
        </span>
      </Link>

      <button
        type="button"
        onClick={openSearch}
        aria-label="Search and commands"
        className="mx-1 mb-3.5 flex items-center gap-2 rounded-xl border border-[rgba(20,22,30,0.07)] bg-white/72 px-2.5 py-2 text-xs text-[#4a4e58] shadow-[0_1px_2px_rgba(0,0,0,0.03)] transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--lore-lavender)] dark:border-white/10 dark:bg-white/7 dark:text-[#b4b8c5] dark:hover:bg-white/10"
      >
        <SearchIcon className="size-3.5 shrink-0" aria-hidden="true" />
        <span className="flex-1 text-left">Search &amp; Commands…</span>
        <kbd className="rounded-md bg-[rgba(20,22,30,0.05)] px-1.5 py-0.5 text-[10.5px] font-semibold text-[#555964] dark:bg-white/10 dark:text-[#a8acb8]">
          ⌘K
        </kbd>
      </button>

      <nav aria-label="Main" className="flex min-h-0 flex-1 flex-col">
        <div className="mx-1 mb-3.5 flex flex-col gap-1">
          {primary.map((item) => (
            <PrimaryLink key={item.href} item={item} active={isCurrent(item.href, pathname)} />
          ))}
        </div>

        <NavGroup label="Library" items={library} pathname={pathname} />
        <NavGroup label="Project" items={project} pathname={pathname} />

        <div className="mx-1 mb-3" role="group" aria-labelledby="nav-group-platform">
          <div
            id="nav-group-platform"
            className="px-2.5 py-1.5 text-[10px] font-bold tracking-[0.08em] text-[#5a5e68] uppercase dark:text-[#9aa0b0]"
          >
            Platform
          </div>
          <SubLink
            item={{ href: "/settings", title: "Settings", icon: SettingsIcon, tone: "rose" }}
            active={settingsCurrent}
          />
        </div>
      </nav>

      <div className="mt-auto px-1">
        <div
          className="flex items-center justify-between gap-2 rounded-xl border border-[rgba(20,22,30,0.06)] bg-white/68 px-2.5 py-2 dark:border-white/7 dark:bg-white/7"
          role="group"
          aria-label="Color theme"
        >
          <span className="text-[11px] font-semibold text-[#3f434c] dark:text-[#c2c5d0]">Theme</span>
          <div className="inline-flex items-center gap-0.5 rounded-full bg-[rgba(20,22,30,0.05)] p-0.5 dark:bg-white/10">
            <button
              type="button"
              onClick={() => setTheme("dark")}
              title="Dark theme"
              aria-label="Dark theme"
              aria-pressed={isDark}
              className={cn(
                "grid size-7 place-items-center rounded-full transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#5f52c4] dark:focus-visible:ring-[#c4bcf8]",
                isDark
                  ? "bg-card text-foreground shadow-sm"
                  : "text-[#555964] hover:text-[#18191d] dark:text-[#a8acb8]"
              )}
            >
              <MoonIcon className="size-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setTheme("light")}
              title="Light theme"
              aria-label="Light theme"
              aria-pressed={!isDark}
              className={cn(
                "grid size-7 place-items-center rounded-full transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#5f52c4] dark:focus-visible:ring-[#c4bcf8]",
                !isDark
                  ? "bg-white text-[#18191d] shadow-sm"
                  : "text-[#555964] hover:text-[#f3f4f8]"
              )}
            >
              <SunIcon className="size-3.5" />
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}

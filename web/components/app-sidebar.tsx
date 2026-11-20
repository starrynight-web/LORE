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

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

const main = [
  { href: "/", title: "Dashboard", icon: LayoutDashboardIcon },
  { href: "/personas", title: "Personas", icon: UsersIcon },
  { href: "/skills", title: "Skills", icon: LibraryIcon },
  { href: "/codebase", title: "Codebase", icon: FolderTreeIcon },
  { href: "/replay", title: "Decisions", icon: HistoryIcon },
]

function isCurrent(href: string, pathname: string) {
  if (href === "/") return pathname === "/"
  return pathname === href || pathname.startsWith(`${href}/`)
}

function RailItem({
  href,
  title,
  active,
  icon: Icon,
}: {
  href: string
  title: string
  active: boolean
  icon: React.ComponentType<{ className?: string }>
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Link
            href={href}
            aria-label={title}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex size-[42px] items-center justify-center rounded-full transition-all duration-150",
              active
                ? "bg-[#1c1d21] text-white shadow-[0_6px_16px_rgba(0,0,0,0.14)] dark:bg-[#f3f4f8] dark:text-[#14151a]"
                : "bg-white/75 text-muted-foreground shadow-[0_2px_8px_rgba(0,0,0,0.03)] hover:bg-white hover:text-foreground dark:bg-white/8 dark:hover:bg-white/16"
            )}
          />
        }
      >
        <Icon className="size-[18px]" />
      </TooltipTrigger>
      <TooltipContent side="right">{title}</TooltipContent>
    </Tooltip>
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

  return (
    <aside
      aria-label="Primary navigation"
      className="sticky top-0 z-20 hidden h-screen w-[76px] shrink-0 flex-col items-center px-2.5 py-5 md:flex"
    >
      <Link
        href="/"
        aria-label="Lore home"
        className="mb-6 flex size-10 items-center justify-center rounded-[10px] text-foreground transition-opacity hover:opacity-80"
      >
        <svg
          width="38"
          height="38"
          viewBox="2.5 2.5 19 19"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M18.96 14.35A7.35 7.35 0 1 1 9.65 5.04"
            className="stroke-muted-foreground/30"
            strokeWidth="2.1"
            strokeLinecap="round"
          />
          <path
            d="M12.3 4.66A7.35 7.35 0 0 1 19.34 11.7"
            className="stroke-[#658f12] dark:stroke-[#c8eb5e]"
            strokeWidth="2.1"
            strokeLinecap="round"
          />
          <path
            d="M9.6 8.3V15.3H15.2"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </Link>

      <nav className="flex flex-1 flex-col items-center gap-2.5">
        {main.map((item) => (
          <RailItem
            key={item.href}
            href={item.href}
            title={item.title}
            active={isCurrent(item.href, pathname)}
            icon={item.icon}
          />
        ))}
      </nav>

      <div className="mt-auto flex flex-col items-center gap-3">
        <div
          className="flex flex-col items-center gap-1 rounded-full bg-white/75 p-1 shadow-[0_2px_8px_rgba(0,0,0,0.04)] backdrop-blur-sm dark:bg-white/8"
          role="group"
          aria-label="Color theme"
        >
          <button
            type="button"
            onClick={() => setTheme("dark")}
            title="Dark mode"
            aria-label="Dark mode"
            aria-pressed={isDark}
            className={cn(
              "grid size-7 place-items-center rounded-full transition-all",
              isDark
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <MoonIcon className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setTheme("light")}
            title="Light mode"
            aria-label="Light mode"
            aria-pressed={!isDark}
            className={cn(
              "grid size-7 place-items-center rounded-full transition-all",
              !isDark
                ? "bg-white text-[#18191d] shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <SunIcon className="size-3.5" />
          </button>
        </div>

        <RailItem
          href="/settings"
          title="Settings"
          active={settingsCurrent}
          icon={SettingsIcon}
        />
      </div>
    </aside>
  )
}

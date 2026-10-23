"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  CableIcon,
  CommandIcon,
  FolderTreeIcon,
  HistoryIcon,
  LayoutDashboardIcon,
  SettingsIcon,
  UsersIcon,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"

const main = [
  { href: "/", title: "Setup", icon: LayoutDashboardIcon },
  { href: "/personas", title: "Personas", icon: UsersIcon },
  { href: "/codebase", title: "Codebase", icon: FolderTreeIcon },
  { href: "/replay", title: "Replay", icon: HistoryIcon },
  { href: "/connect", title: "Connect", icon: CableIcon },
]

function current(href: string, pathname: string) {
  if (href === "/") return pathname === "/"
  return pathname === href || pathname.startsWith(`${href}/`)
}

export function AppSidebar() {
  const pathname = usePathname()
  const settingsCurrent = current("/settings", pathname)

  return (
    <Sidebar variant="inset" collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              tooltip="Lore"
              render={<Link href="/" />}
            >
              <CommandIcon />
              <span className="text-base font-medium">Lore</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {main.map((item) => {
                const active = current(item.href, pathname)
                const Icon = item.icon
                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      isActive={active}
                      tooltip={item.title}
                      aria-current={active ? "page" : undefined}
                      render={<Link href={item.href} />}
                    >
                      <Icon />
                      <span>{item.title}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={settingsCurrent}
              tooltip="Settings"
              aria-current={settingsCurrent ? "page" : undefined}
              render={<Link href="/settings" />}
            >
              <SettingsIcon />
              <span>Settings</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}

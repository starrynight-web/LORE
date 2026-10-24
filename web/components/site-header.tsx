"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"

const titles: { prefix: string; title: string }[] = [
  { prefix: "/personas", title: "Personas" },
  { prefix: "/skills", title: "Skills" },
  { prefix: "/codebase", title: "Codebase" },
  { prefix: "/settings", title: "Settings" },
]

export function pageTitle(pathname: string) {
  if (pathname.startsWith("/personas/")) return "Persona"
  if (pathname.startsWith("/skills/")) return "Skill"
  if (pathname.startsWith("/codebase/")) return "Codebase"
  const match = titles.find((item) => pathname === item.prefix || pathname.startsWith(`${item.prefix}/`))
  return match?.title ?? "Dashboard"
}

export function SiteHeader() {
  const title = pageTitle(usePathname())

  return (
    <header className="flex h-(--header-height) shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear">
      <div className="flex w-full items-center gap-1 px-4 lg:gap-2 lg:px-6">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mx-2 data-[orientation=vertical]:h-4" />
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink render={<Link href="/" />}>Lore</BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{title}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <h1 className="sr-only">{title}</h1>
      </div>
    </header>
  )
}

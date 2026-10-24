"use client"

import { useEffect, useState } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { Onboarding } from "@/components/onboarding"
import { SiteHeader } from "@/components/site-header"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { api, type Onboarding as OnboardingState } from "@/lib/api"

export function Shell({ children }: { children: React.ReactNode }) {
  const [setup, setSetup] = useState<OnboardingState | null>(null)

  useEffect(() => {
    api<OnboardingState>("/api/onboarding")
      .then(setSetup)
      .catch(() => setSetup({ completed: true, step: "done" }))
  }, [])

  const showWelcome = setup !== null && setup.completed === false

  return (
    <SidebarProvider
      style={
        {
          "--sidebar-width": "calc(var(--spacing) * 72)",
          "--header-height": "calc(var(--spacing) * 12)",
        } as React.CSSProperties
      }
    >
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-3 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:ring-2"
      >
        Skip to content
      </a>
      <AppSidebar />
      <SidebarInset>
        <SiteHeader />
        <div className="flex flex-1 flex-col">
          <div className="@container/main flex flex-1 flex-col gap-2">
            <div id="content" className="flex flex-col gap-4 px-4 py-4 md:gap-6 md:py-6 lg:px-6">
              {children}
            </div>
          </div>
        </div>
      </SidebarInset>
      {showWelcome && setup ? (
        <Onboarding initial={setup} onDone={() => setSetup({ completed: true, step: "done" })} />
      ) : null}
    </SidebarProvider>
  )
}

"use client"

import { useEffect, useState } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { Onboarding } from "@/components/onboarding"
import { SiteHeader } from "@/components/site-header"
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
    <div className="relative flex min-h-screen w-full">
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 -z-10 backdrop-blur-[22px]"
        style={{ background: "var(--lore-shell)" }}
      />
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-3 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:ring-2"
      >
        Skip to content
      </a>
      <AppSidebar />
      <div className="mx-auto flex min-w-0 w-full max-w-[1280px] flex-1 flex-col px-4 pt-[22px] pb-16 sm:px-7">
        <SiteHeader />
        <main id="content" className="flex flex-1 flex-col gap-[18px]">
          {children}
        </main>
      </div>
      {showWelcome && setup ? (
        <Onboarding initial={setup} onDone={() => setSetup({ completed: true, step: "done" })} />
      ) : null}
    </div>
  )
}

"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import {
  ArrowUpRightIcon,
  BarChart3Icon,
  CheckIcon,
  ChevronDownIcon,
  CopyIcon,
  LibraryIcon,
  PlusIcon,
  SlidersHorizontalIcon,
  UsersIcon,
} from "lucide-react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Onboarding } from "@/components/onboarding"
import { Shell } from "@/components/Shell"
import { SkillBarChart } from "@/components/skill-bar-chart"
import { TokenSplineChart } from "@/components/token-spline-chart"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { api, type Persona, type Skill, type Usage } from "@/lib/api"
import { personaHref } from "@/lib/routes"
import { cn } from "@/lib/utils"

export default function DashboardPage() {
  const [usage, setUsage] = useState<Usage | null>(null)
  const [command, setCommand] = useState("")
  const [prompt, setPrompt] = useState("")
  const [personas, setPersonas] = useState<Persona[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [waitingCount, setWaitingCount] = useState(0)
  const [budget, setBudget] = useState<number>(800)
  const [notchTab, setNotchTab] = useState<"connect" | "mcp" | "store">("connect")
  const [modal, setModal] = useState<"skills" | "persona" | null>(null)
  const [error, setError] = useState("")

  const reload = useCallback(() => {
    api<Usage>("/api/stats")
      .then(setUsage)
      .catch((exc: Error) => setError(exc.message))
    api<{ command?: string; prompt: string }>("/api/connect")
      .then((row) => {
        setCommand(row.command ?? "")
        setPrompt(row.prompt)
      })
      .catch((exc: Error) => setError(exc.message))
    api<{ personas: Persona[] }>("/api/personas")
      .then((res) => setPersonas(res.personas ?? []))
      .catch(() => {})
    api<{ skills: Skill[]; waiting?: unknown[] }>("/api/skills")
      .then((res) => {
        setSkills(res.skills ?? [])
        setWaitingCount((res.waiting ?? []).length)
      })
      .catch(() => {})
    api<{ token_budget?: number }>("/api/settings")
      .then((res) => {
        if (typeof res.token_budget === "number") setBudget(res.token_budget)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const stableSkillsCount = useMemo(
    () => skills.filter((s) => s.status === "stable").length,
    [skills]
  )
  const installedSkillsCount = skills.length + waitingCount
  const activeBudget = usage?.tokens?.budget ?? budget
  const tokensAvg = usage?.tokens?.avg ?? 0
  const tokensMax = usage?.tokens?.max ?? 0

  const connectCmd = command || "lore-solo connect"

  const copyCommand = () => {
    navigator.clipboard.writeText(connectCmd).then(
      () => toast.success("Copied connect command"),
      () => toast.error("Could not copy to clipboard")
    )
  }

  const copyPrompt = () => {
    navigator.clipboard.writeText(prompt || connectCmd).then(
      () => toast.success("Copied agent prompt"),
      () => toast.error("Could not copy to clipboard")
    )
  }

  return (
    <Shell>
      <ErrorAlert message={error} />

      {/* HERO ROW */}
      <div className="flex flex-wrap items-end justify-between gap-5 pt-1">
        <div>
          <h1 className="text-[30px] font-bold tracking-[-0.03em] leading-[1.15]">
            Dashboard
          </h1>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Let&apos;s make this coding session productive.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-7">
          <div>
            <div className="text-[11.5px] text-muted-foreground">Installed skills</div>
            <div className="text-[26px] font-bold tabular-nums">
              {installedSkillsCount}
              {waitingCount > 0 ? (
                <span className="ml-1.5 text-xs font-medium text-muted-foreground">
                  ({waitingCount} inbox)
                </span>
              ) : null}
            </div>
          </div>
          <div>
            <div className="text-[11.5px] text-muted-foreground">Created personas</div>
            <div className="text-[26px] font-bold tabular-nums">{personas.length}</div>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button className="rounded-full px-4 py-2 text-[13px] font-semibold" />
              }
            >
              <PlusIcon className="size-4" />
              Add
              <ChevronDownIcon className="size-3.5 opacity-75" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48 rounded-2xl p-1.5">
              <DropdownMenuItem
                onClick={() => setModal("skills")}
                className="cursor-pointer rounded-xl px-3 py-2 text-[13px] font-medium"
              >
                <LibraryIcon className="size-4" />
                Add skill
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => setModal("persona")}
                className="cursor-pointer rounded-xl px-3 py-2 text-[13px] font-medium"
              >
                <UsersIcon className="size-4" />
                Create persona
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* TOP BENTO ROW */}
      <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[0.95fr_1.55fr]">
        {/* EDITOR & MCP QUICKSTART CARD */}
        <Card className="flex min-h-[290px] flex-col justify-between px-[22px] py-5">
          <div>
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="inline-flex items-center gap-1 rounded-full bg-muted p-1">
                <button
                  type="button"
                  onClick={() => setNotchTab("connect")}
                  className={cn(
                    "rounded-full px-3 py-1.5 text-xs font-semibold transition-all",
                    notchTab === "connect"
                      ? "bg-card text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  Connect IDE
                </button>
                <button
                  type="button"
                  onClick={() => setNotchTab("mcp")}
                  className={cn(
                    "rounded-full px-3 py-1.5 text-xs font-semibold transition-all",
                    notchTab === "mcp"
                      ? "bg-card text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  MCP
                </button>
                <button
                  type="button"
                  onClick={() => setNotchTab("store")}
                  className={cn(
                    "rounded-full px-3 py-1.5 text-xs font-semibold transition-all",
                    notchTab === "store"
                      ? "bg-card text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  Store
                </button>
              </div>
              <Link
                href="/connect"
                aria-label="Open connect settings"
                className="grid size-9 place-items-center rounded-full border border-border bg-card text-foreground transition-transform hover:scale-105"
              >
                <ArrowUpRightIcon className="size-4" />
              </Link>
            </div>

            {notchTab === "connect" ? (
              <div className="flex flex-col gap-3">
                <div>
                  <div className="text-[15px] font-semibold tracking-[-0.01em]">
                    Connect your editor
                  </div>
                  <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                    Registers Lore MCP and standing rules with installed IDEs.
                  </p>
                </div>
                <div className="flex items-center justify-between gap-2 rounded-2xl border border-border bg-muted/70 px-3.5 py-2.5">
                  <code className="truncate font-mono text-xs text-foreground">
                    {connectCmd}
                  </code>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={copyCommand}
                    className="shrink-0 rounded-full px-3 text-xs"
                  >
                    <CopyIcon className="size-3" />
                    Copy
                  </Button>
                </div>
              </div>
            ) : notchTab === "mcp" ? (
              <div className="flex flex-col gap-2.5">
                <div className="text-[15px] font-semibold tracking-[-0.01em]">
                  MCP surfaces &amp; budget
                </div>
                <div className="grid grid-cols-2 gap-2.5 text-xs">
                  <div className="rounded-2xl bg-muted/70 p-3">
                    <div className="font-semibold text-foreground">Coding (default)</div>
                    <div className="mt-0.5 text-muted-foreground">
                      5 tools · {activeBudget} tok/call cap
                    </div>
                  </div>
                  <div className="rounded-2xl bg-muted/70 p-3">
                    <div className="font-semibold text-foreground">Autonomous (--full)</div>
                    <div className="mt-0.5 text-muted-foreground">
                      Install, persona, scan, approve
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-2.5">
                <div className="text-[15px] font-semibold tracking-[-0.01em]">
                  Store readiness
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  <div className="rounded-2xl bg-muted/70 p-3">
                    <div className="text-muted-foreground">Stable</div>
                    <div className="mt-0.5 text-lg font-bold tabular-nums">
                      {stableSkillsCount}
                    </div>
                  </div>
                  <div className="rounded-2xl bg-muted/70 p-3">
                    <div className="text-muted-foreground">Inbox</div>
                    <div className="mt-0.5 text-lg font-bold tabular-nums">
                      {waitingCount}
                    </div>
                  </div>
                  <div className="rounded-2xl bg-muted/70 p-3">
                    <div className="text-muted-foreground">Personas</div>
                    <div className="mt-0.5 text-lg font-bold tabular-nums">
                      {personas.length}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="mt-4 flex items-center justify-between gap-3 border-t border-border pt-3.5">
            <span className="text-xs text-muted-foreground">
              {notchTab === "connect"
                ? "Need the full agent prompt?"
                : notchTab === "mcp"
                  ? "Tune token cap & draft provider"
                  : "Review & approve waiting drafts"}
            </span>
            {notchTab === "connect" ? (
              <Button size="sm" variant="outline" onClick={copyPrompt} className="rounded-full px-3.5 text-xs">
                <CopyIcon className="size-3" />
                Copy prompt
              </Button>
            ) : notchTab === "mcp" ? (
              <Button size="sm" variant="outline" render={<Link href="/settings" />} className="rounded-full px-3.5 text-xs">
                Settings
              </Button>
            ) : (
              <Button size="sm" variant="outline" render={<Link href="/skills" />} className="rounded-full px-3.5 text-xs">
                Open skills
              </Button>
            )}
          </div>
        </Card>

        {/* MOST CALLED SKILLS BAR CHART CARD */}
        <Card className="px-[22px] py-5">
          <div className="mb-3.5 flex items-start justify-between gap-3">
            <div>
              <div className="text-[15px] font-semibold tracking-[-0.01em]">Most called skills</div>
              <div className="mt-0.5 text-[12.5px] text-muted-foreground">
                Skills most frequently served into agent context
              </div>
            </div>
            <Link
              href="/skills"
              aria-label="Open skills"
              className="grid size-9 place-items-center rounded-full border border-border bg-card text-foreground transition-transform hover:scale-105"
            >
              <BarChart3Icon className="size-4" />
            </Link>
          </div>
          <SkillBarChart rows={usage?.skills ?? []} />
        </Card>
      </div>

      {/* BOTTOM BENTO ROW */}
      <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[0.95fr_1.55fr]">
        {/* PERSONAS CARD */}
        <Card className="px-[22px] py-5">
          <div className="mb-3.5 flex items-start justify-between gap-3">
            <div>
              <div className="text-[15px] font-semibold tracking-[-0.01em]">Personas</div>
              <div className="mt-0.5 text-[12.5px] text-muted-foreground">
                Roles routing your approved skills
              </div>
            </div>
            <Link
              href="/personas"
              aria-label="Open personas"
              className="grid size-9 place-items-center rounded-full border border-border bg-card text-foreground transition-transform hover:scale-105"
            >
              <ArrowUpRightIcon className="size-4" />
            </Link>
          </div>

          {personas.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No personas yet.{" "}
              <Link href="/personas" className="underline">
                Create one
              </Link>{" "}
              or let your agent call <code className="font-mono text-xs">setup_persona</code>.
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              {personas.slice(0, 4).map((p) => {
                const isStable = p.status === "stable"
                return (
                  <Link
                    key={p.id}
                    href={personaHref(p.id)}
                    className="flex items-center justify-between gap-3 rounded-xl px-1.5 py-1 transition-colors hover:bg-muted/60"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-[13.5px] font-semibold">{p.title}</div>
                      <div className="truncate text-[12px] text-muted-foreground">
                        {p.summary || `${p.skill_ids.length} skill(s)`}
                      </div>
                    </div>
                    <span
                      title={p.status}
                      className={cn(
                        "grid size-[26px] shrink-0 place-items-center rounded-full text-xs font-bold",
                        isStable
                          ? "bg-[var(--lore-sage)] text-[#1a2e1c]"
                          : "bg-amber-500/20 text-amber-600 dark:text-amber-400"
                      )}
                    >
                      {isStable ? <CheckIcon className="size-3.5" /> : "•"}
                    </span>
                  </Link>
                )
              })}
            </div>
          )}
        </Card>

        {/* SUMMARY / TOKEN TELEMETRY SPLINE CARD */}
        <Card className="px-[22px] py-5">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[15px] font-semibold tracking-[-0.01em]">Summary</div>
              <div className="mt-0.5 text-[12.5px] text-muted-foreground">
                Token telemetry across <code className="font-mono text-xs">get_context</code> calls
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-3 rounded-full bg-muted px-3 py-1 text-[11.5px] text-muted-foreground">
                <span>
                  Calls <strong className="text-foreground tabular-nums">{usage?.calls ?? 0}</strong>
                </span>
                <span>
                  Avg <strong className="text-foreground tabular-nums">{tokensAvg}</strong>
                </span>
                <span>
                  Peak <strong className="text-foreground tabular-nums">{tokensMax}</strong>
                </span>
              </div>
              <Link
                href="/settings"
                title="Budget settings"
                aria-label="Budget settings"
                className="grid size-9 place-items-center rounded-full border border-border bg-card text-foreground transition-transform hover:scale-105"
              >
                <SlidersHorizontalIcon className="size-4" />
              </Link>
            </div>
          </div>

          <TokenSplineChart series={usage?.tokens?.series ?? []} budget={activeBudget} />
        </Card>
      </div>

      {modal ? (
        <Onboarding
          panel={modal}
          initial={{ completed: true, step: "done" }}
          onDone={() => {
            const kind = modal
            setModal(null)
            toast.success(kind === "persona" ? "Persona saved as a draft." : "Skills added.")
            reload()
          }}
          onClose={() => setModal(null)}
        />
      ) : null}
    </Shell>
  )
}

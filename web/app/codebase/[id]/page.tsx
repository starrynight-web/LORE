"use client"

import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import { useTheme } from "next-themes"
import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowLeftIcon, CheckIcon, RefreshCwIcon, Trash2Icon } from "lucide-react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api, type Codebase } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export default function CodebaseDetailPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const id = decodeURIComponent(params.id)
  const { resolvedTheme } = useTheme()
  const iframeRef = useRef<HTMLIFrameElement | null>(null)
  const [row, setRow] = useState<Codebase | null>(null)
  const [name, setName] = useState("")
  const [error, setError] = useState("")

  const reload = useCallback(() => {
    api<Codebase>(`/api/codebases/${encodeURIComponent(id)}`)
      .then((loaded) => {
        setRow(loaded)
        setName(loaded.name)
      })
      .catch((exc: Error) => setError(exc.message))
  }, [id])

  useEffect(() => {
    reload()
  }, [reload])

  useEffect(() => {
    if (row?.map.state !== "running") return
    const timer = window.setInterval(reload, 1000)
    return () => window.clearInterval(timer)
  }, [row?.map.state, reload])

  const syncGraphTheme = useCallback(() => {
    const mode = resolvedTheme === "dark" ? "dark" : "light"
    try {
      window.localStorage.setItem("graphify-theme", mode)
    } catch {
      // ignore storage errors
    }
    const doc = iframeRef.current?.contentDocument
    if (!doc) return
    const btn = doc.querySelector<HTMLButtonElement>(`[data-theme-choice="${mode}"]`)
    if (btn) {
      btn.click()
    } else {
      doc.documentElement.setAttribute("data-theme", mode)
    }
  }, [resolvedTheme])

  useEffect(() => {
    syncGraphTheme()
  }, [syncGraphTheme])

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api(`/api/codebases/${encodeURIComponent(id)}`, {
      method: "POST",
      body: JSON.stringify({ name }),
    })
    toast.success("Name updated.")
    reload()
  }

  async function build() {
    setError("")
    await api(`/api/codebases/${encodeURIComponent(id)}`, {
      method: "POST",
      body: JSON.stringify({ build: true }),
    })
    reload()
  }

  async function remove() {
    setError("")
    await api(`/api/codebases/${encodeURIComponent(id)}`, { method: "DELETE" })
    toast.success("Codebase removed.")
    router.push("/codebase")
  }

  const links = row?.map.links ?? []
  const ready = row?.map.state === "ready"
  const running = row?.map.state === "running"

  return (
    <Shell>
      <ErrorAlert message={error} />
      {row ? (
        <>
          {/* HERO ROW */}
          <div className="flex flex-wrap items-end justify-between gap-4 pt-1">
            <div className="min-w-0">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Link
                  href="/codebase"
                  className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  <ArrowLeftIcon className="size-3.5" />
                  Codebase
                </Link>
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold",
                    ready
                      ? "bg-[#c8eb5e] text-[#141517]"
                      : running
                        ? "bg-[#a59bf3]/30 text-foreground"
                        : "bg-muted text-muted-foreground"
                  )}
                >
                  {ready ? <CheckIcon className="size-3" /> : null}
                  {row.map.state}
                </span>
              </div>
              <h1 className="truncate text-[30px] font-bold tracking-[-0.03em] leading-[1.15]">
                {row.name}
              </h1>
              <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
                {row.path}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2.5">
              <Button
                type="button"
                disabled={running}
                onClick={() => build().catch((exc: Error) => setError(exc.message))}
              >
                <RefreshCwIcon className={cn("size-3.5", running && "animate-spin")} />
                {ready ? "Update map" : running ? "Mapping…" : "Map codebase"}
              </Button>
              <button
                type="button"
                onClick={() => remove().catch((exc: Error) => setError(exc.message))}
                aria-label="Delete codebase"
                title="Delete codebase"
                className="grid size-9 place-items-center rounded-full border border-border bg-card text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2Icon className="size-4" />
              </button>
            </div>
          </div>

          {row.map.error ? (
            <Card className="border-destructive/40 bg-destructive/5 px-[22px] py-4 text-sm text-destructive">
              {row.map.error}
            </Card>
          ) : null}

          {/* RENAME & INFO BENTO */}
          <Card className="px-[22px] py-5">
            <form
              className="flex flex-col gap-3 sm:flex-row sm:items-end"
              onSubmit={(event) => save(event).catch((exc: Error) => setError(exc.message))}
            >
              <div className="flex-1">
                <label htmlFor="name" className="mb-1.5 block text-xs font-semibold text-muted-foreground">
                  Display name
                </label>
                <Input
                  id="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                  className="h-10 rounded-full bg-muted/60 px-4"
                />
              </div>
              <Button type="submit" variant="secondary" className="h-10 px-5">
                Save name
              </Button>
            </form>
          </Card>

          {/* GRAPH MAP CARD */}
          {ready ? (
            <Card className="overflow-hidden px-[22px] py-5">
              <div className="mb-3.5 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Codebase map</h2>
                  <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                    Interactive dependency &amp; community graph synced with your theme.
                  </p>
                </div>
              </div>
              <iframe
                ref={iframeRef}
                onLoad={syncGraphTheme}
                title="Codebase map"
                src={`/api/codebases/${encodeURIComponent(id)}/graph`}
                className="h-[540px] w-full rounded-2xl border border-border bg-background"
              />
            </Card>
          ) : null}

          {/* LINKS CARD */}
          {links.length > 0 ? (
            <Card className="px-[22px] py-5">
              <div className="mb-3.5">
                <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Links</h2>
                <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                  Extracted links were read from the code. Inferred links were guessed.
                </p>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>From</TableHead>
                    <TableHead>Relation</TableHead>
                    <TableHead>To</TableHead>
                    <TableHead className="text-right">Confidence</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {links.map((link) => (
                    <TableRow key={`${link.node}-${link.relation}-${link.to}`}>
                      <TableCell className="font-mono text-xs">{link.node}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{link.relation}</TableCell>
                      <TableCell className="font-mono text-xs">{link.to}</TableCell>
                      <TableCell className="text-right">
                        <span
                          className={cn(
                            "inline-flex rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold",
                            link.confidence === "EXTRACTED"
                              ? "bg-[#c8eb5e]/35 text-foreground"
                              : "bg-muted text-muted-foreground"
                          )}
                        >
                          {link.confidence}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          ) : null}
        </>
      ) : (
        <Card className="p-6 text-sm text-muted-foreground">Loading codebase…</Card>
      )}
    </Shell>
  )
}

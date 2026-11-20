"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { ArrowUpRightIcon, CheckIcon, FolderIcon, Trash2Icon } from "lucide-react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Onboarding } from "@/components/onboarding"
import { PageHero } from "@/components/page-hero"
import { Shell } from "@/components/Shell"
import { api, type Codebase } from "@/lib/api"
import { codebaseHref } from "@/lib/routes"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

function folderName(path: string) {
  const parts = path.split(/[/\\]/).filter(Boolean)
  return parts[parts.length - 1] ?? "Folder"
}

export default function CodebasePage() {
  const [rows, setRows] = useState<Codebase[]>([])
  const [error, setError] = useState("")
  const [open, setOpen] = useState(false)

  function reload() {
    api<{ codebases: Codebase[] }>("/api/codebases")
      .then((row) => setRows(row.codebases))
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
  }, [])

  async function remove(id: string) {
    setError("")
    await api(`/api/codebases/${encodeURIComponent(id)}`, { method: "DELETE" })
    toast.success("Codebase and its map files were removed.")
    reload()
  }

  return (
    <Shell>
      <ErrorAlert message={error} />
      <PageHero
        title="Codebase"
        subtitle="Choose a folder. Lore can build a map inside it. Your files stay where they are."
        action={
          <Button type="button" onClick={() => setOpen(true)}>
            + Add project
          </Button>
        }
      />
      <section className="flex flex-col gap-3">
        {rows.length === 0 ? (
          <Card className="p-6 text-sm text-muted-foreground">
            No project yet. Add a folder, then open it to build the map.
          </Card>
        ) : null}
        <div className="grid grid-cols-1 gap-[18px] md:grid-cols-2 lg:grid-cols-3">
          {rows.map((row) => {
            const isReady = row.map.state === "ready"
            return (
              <Card key={row.id} className="flex flex-col justify-between gap-4 px-[22px] py-5">
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold",
                        isReady
                          ? "bg-[var(--lore-sage)] text-[#1a2e1c]"
                          : "bg-muted text-muted-foreground"
                      )}
                    >
                      {isReady ? <CheckIcon className="size-3" /> : null}
                      {row.map.state}
                    </span>
                    <span className="inline-flex items-center gap-1 text-[11.5px] text-muted-foreground">
                      <FolderIcon className="size-3" />
                      {folderName(row.path)}
                    </span>
                  </div>
                  <h2 className="mt-2.5 truncate text-[16px] font-semibold tracking-[-0.01em]">
                    <Link href={codebaseHref(row.id)} className="hover:underline">
                      {row.name}
                    </Link>
                  </h2>
                  <p className="mt-1 truncate font-mono text-[11.5px] text-muted-foreground">
                    {row.path}
                  </p>
                </div>

                <div className="flex items-center justify-between border-t border-border pt-3">
                  <button
                    type="button"
                    onClick={() => remove(row.id).catch((exc: Error) => setError(exc.message))}
                    aria-label={`Delete ${row.name}`}
                    className="grid size-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2Icon className="size-4" />
                  </button>
                  <Link
                    href={codebaseHref(row.id)}
                    className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-semibold text-foreground transition-colors hover:bg-muted"
                  >
                    Open
                    <ArrowUpRightIcon className="size-3.5" />
                  </Link>
                </div>
              </Card>
            )
          })}
        </div>
      </section>
      {open ? (
        <Onboarding
          panel="codebase"
          initial={{ completed: true, step: "done" }}
          onDone={() => {
            setOpen(false)
            toast.success("Project added.")
            reload()
          }}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </Shell>
  )
}

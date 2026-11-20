"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { ArrowUpRightIcon, CheckIcon, PlusIcon, Trash2Icon } from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/confirm-dialog"
import { ErrorAlert } from "@/components/error-alert"
import { Onboarding } from "@/components/onboarding"
import { PageHero } from "@/components/page-hero"
import { Shell } from "@/components/Shell"
import { api, type Persona } from "@/lib/api"
import { personaHref } from "@/lib/routes"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

type Ready = { id: string; title: string; summary: string }

export default function PersonasPage() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [ready, setReady] = useState<Ready[]>([])
  const [error, setError] = useState("")
  const [open, setOpen] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<Persona | null>(null)
  const [deleting, setDeleting] = useState(false)

  function reload() {
    api<{ personas: Persona[] }>("/api/personas")
      .then((data) => setPersonas(data.personas))
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
    api<{ personas: Ready[] }>("/api/catalog")
      .then((data) => setReady(data.personas))
      .catch((exc: Error) => setError(exc.message))
  }, [])

  async function addReady(id: string) {
    setError("")
    await api(`/api/catalog/${encodeURIComponent(id)}`, { method: "POST" })
    toast.success("Starter added.")
    reload()
  }

  async function remove(persona: Persona) {
    setError("")
    setDeleting(true)
    try {
      await api(`/api/personas/${encodeURIComponent(persona.id)}`, { method: "DELETE" })
      setPendingDelete(null)
      toast.success("Persona removed. Its skills are waiting for a new role.")
      reload()
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Shell>
      <ErrorAlert message={error} />
      <PageHero
        title="Personas"
        subtitle="A persona is a role. It can only use the skills you attach to it."
        action={
          <Button type="button" onClick={() => setOpen(true)}>
            + New persona
          </Button>
        }
      />
      <section className="flex flex-col gap-3">
        {personas.length === 0 ? (
          <Card className="p-6 text-sm text-muted-foreground">
            No personas yet. Create one, or add a starter below.
          </Card>
        ) : null}
        <div className="grid grid-cols-1 gap-[18px] md:grid-cols-2 lg:grid-cols-3">
          {personas.map((persona) => {
            const isStable = persona.status === "stable"
            return (
              <Card key={persona.id} className="flex flex-col justify-between gap-4 px-[22px] py-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold",
                          isStable
                            ? "bg-[var(--lore-sage)] text-[#1a2e1c]"
                            : "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                        )}
                      >
                        {isStable ? <CheckIcon className="size-3" /> : null}
                        {isStable ? "ready" : "draft"}
                      </span>
                      <span className="text-[11.5px] text-muted-foreground">
                        {persona.skill_ids.length} skill{persona.skill_ids.length === 1 ? "" : "s"}
                      </span>
                    </div>
                    <h2 className="mt-2.5 truncate text-[16px] font-semibold tracking-[-0.01em]">
                      <Link href={personaHref(persona.id)} className="hover:underline">
                        {persona.title}
                      </Link>
                    </h2>
                    <p className="mt-1 line-clamp-2 text-[12.5px] text-muted-foreground">
                      {persona.summary || "No summary yet."}
                    </p>
                  </div>
                </div>

                <div className="flex items-center justify-between border-t border-border pt-3">
                  <button
                    type="button"
                    onClick={() => setPendingDelete(persona)}
                    aria-label={`Delete ${persona.title}`}
                    className="grid size-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2Icon className="size-4" />
                  </button>
                  <Link
                    href={personaHref(persona.id)}
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

      {ready.length > 0 ? (
        <section className="flex flex-col gap-3 pt-2">
          <div>
            <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Starter personas</h2>
            <p className="text-[12.5px] text-muted-foreground">One-click templates you can customize and approve.</p>
          </div>
          <div className="grid grid-cols-1 gap-[18px] md:grid-cols-2">
            {ready.map((persona) => (
              <Card key={persona.id} className="px-[22px] py-5">
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <span className="inline-flex rounded-full bg-[#a59bf3]/25 px-2.5 py-0.5 text-[11px] font-semibold text-foreground">
                      starter
                    </span>
                    <h3 className="mt-2 text-[15px] font-semibold">{persona.title}</h3>
                    <p className="mt-0.5 text-[12.5px] text-muted-foreground">{persona.summary}</p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    className="shrink-0"
                    onClick={() => addReady(persona.id).catch((exc: Error) => setError(exc.message))}
                  >
                    <PlusIcon className="size-3.5" />
                    Add
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </section>
      ) : null}
      {open ? (
        <Onboarding
          panel="persona"
          initial={{ completed: true, step: "done" }}
          onDone={() => {
            setOpen(false)
            toast.success("Persona saved as a draft.")
            reload()
          }}
          onClose={() => setOpen(false)}
        />
      ) : null}
      {pendingDelete ? (
        <ConfirmDialog
          title={`Delete ${pendingDelete.title}?`}
          description={
            pendingDelete.skill_ids.length > 0
              ? `This removes the role. Its ${pendingDelete.skill_ids.length} skill${pendingDelete.skill_ids.length === 1 ? "" : "s"} will go back to waiting so you can attach ${pendingDelete.skill_ids.length === 1 ? "it" : "them"} to another role.`
              : "This removes the role. You can create a new one later."
          }
          confirmLabel="Delete persona"
          busy={deleting}
          onCancel={() => {
            if (!deleting) setPendingDelete(null)
          }}
          onConfirm={() => remove(pendingDelete).catch((exc: Error) => setError(exc.message))}
        />
      ) : null}
    </Shell>
  )
}

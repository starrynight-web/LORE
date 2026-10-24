"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Onboarding } from "@/components/onboarding"
import { Shell } from "@/components/Shell"
import { api, type Persona } from "@/lib/api"
import { personaHref } from "@/lib/routes"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"

type Ready = { id: string; title: string; summary: string }

export default function PersonasPage() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [ready, setReady] = useState<Ready[]>([])
  const [error, setError] = useState("")
  const [open, setOpen] = useState(false)

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

  async function remove(id: string) {
    setError("")
    await api(`/api/personas/${encodeURIComponent(id)}`, { method: "DELETE" })
    toast.success("Persona removed.")
    reload()
  }

  return (
    <Shell>
      <ErrorAlert message={error} />
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-medium">Your personas</h2>
          <p className="text-sm text-muted-foreground">A persona is a role. It can only use the skills you attach to it.</p>
        </div>
        <Button type="button" size="sm" onClick={() => setOpen(true)}>
          New persona
        </Button>
      </div>
      <section className="flex flex-col gap-4">
        {personas.length === 0 ? <p className="text-sm text-muted-foreground">No personas yet. Create one, or add a starter.</p> : null}
        <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
          {personas.map((persona) => (
            <Card key={persona.id}>
              <CardHeader>
                <Badge variant={persona.status === "stable" ? "secondary" : "outline"}>{persona.status === "stable" ? "ready" : "draft"}</Badge>
                <CardTitle>
                  <Link href={personaHref(persona.id)} className="hover:underline">{persona.title}</Link>
                </CardTitle>
                <CardDescription>{persona.summary || "No summary yet."}</CardDescription>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                {persona.skill_ids.length} linked skill{persona.skill_ids.length === 1 ? "" : "s"}
              </CardContent>
              <CardFooter className="gap-2">
                <Button variant="outline" nativeButton={false} render={<Link href={personaHref(persona.id)} />}>Open</Button>
                <Button variant="destructive" type="button" onClick={() => remove(persona.id).catch((exc: Error) => setError(exc.message))}>
                  Delete
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </section>
      <section className="flex flex-col gap-4">
        <h2 className="text-base font-medium">Starters</h2>
        <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
          {ready.map((persona) => (
            <Card key={persona.id}>
              <CardHeader>
                <Badge variant="secondary">starter</Badge>
                <CardTitle>{persona.title}</CardTitle>
                <CardDescription>{persona.summary}</CardDescription>
              </CardHeader>
              <CardFooter>
                <Button type="button" onClick={() => addReady(persona.id).catch((exc: Error) => setError(exc.message))}>
                  Add {persona.title}
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </section>
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
    </Shell>
  )
}

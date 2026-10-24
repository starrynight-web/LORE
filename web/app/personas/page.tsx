"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api, type Persona } from "@/lib/api"
import { personaHref } from "@/lib/routes"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

type Ready = { id: string; title: string; summary: string }

export default function PersonasPage() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [ready, setReady] = useState<Ready[]>([])
  const [name, setName] = useState("")
  const [summary, setSummary] = useState("")
  const [rules, setRules] = useState("")
  const [error, setError] = useState("")

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

  async function create(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api("/api/personas", {
      method: "POST",
      body: JSON.stringify({ name, summary, steps: rules }),
    })
    setName("")
    setSummary("")
    setRules("")
    toast.success("Persona saved as a draft.")
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
      <Card>
        <CardHeader>
          <CardTitle><h2>New persona</h2></CardTitle>
          <CardDescription>A persona is a role. Skills you add later are the only ones that role can use.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={(event) => create(event).catch((exc: Error) => setError(exc.message))}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="persona-name">Name</FieldLabel>
                <Input id="persona-name" value={name} onChange={(event) => setName(event.target.value)} required />
              </Field>
              <Field>
                <FieldLabel htmlFor="persona-summary">Summary</FieldLabel>
                <Input id="persona-summary" value={summary} onChange={(event) => setSummary(event.target.value)} />
              </Field>
              <Field>
                <FieldLabel htmlFor="persona-rules">Rules</FieldLabel>
                <Textarea id="persona-rules" rows={4} value={rules} onChange={(event) => setRules(event.target.value)} />
              </Field>
              <Button type="submit">Create persona</Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
      <section className="flex flex-col gap-4">
        <h2 className="text-base font-medium">Your personas</h2>
        {personas.length === 0 ? <p className="text-sm text-muted-foreground">No personas yet. Create one above, or add a starter.</p> : null}
        <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
          {personas.map((persona) => (
            <Card key={persona.id}>
              <CardHeader>
                <Badge variant={persona.status === "stable" ? "secondary" : "outline"}>{persona.status}</Badge>
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
    </Shell>
  )
}

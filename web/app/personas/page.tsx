"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api, type Persona } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"

type Ready = { id: string; title: string; summary: string }

export default function PersonasPage() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [ready, setReady] = useState<Ready[]>([])
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

  return (
    <Shell>
      <ErrorAlert message={error} />
      <section className="flex flex-col gap-4">
        <h2 className="text-base font-medium">Starters</h2>
        <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
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
      <section className="flex flex-col gap-4">
        <h2 className="text-base font-medium">In this library</h2>
        {personas.length === 0 ? <p className="text-sm text-muted-foreground">No personas yet.</p> : null}
        <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
          {personas.map((persona) => (
            <Card key={persona.id}>
              <CardHeader>
                <Badge variant={persona.status === "stable" ? "secondary" : "outline"}>{persona.status}</Badge>
                <CardTitle>
                  <Link href={`/personas/${encodeURIComponent(persona.id)}`} className="hover:underline">
                    {persona.title}
                  </Link>
                </CardTitle>
                <CardDescription>{persona.summary}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button variant="outline" nativeButton={false} render={<Link href={`/personas/${encodeURIComponent(persona.id)}`} />}>
                  Open
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </Shell>
  )
}

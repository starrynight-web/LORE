"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api, type Persona, type Skill } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

export default function PersonaPage() {
  const params = useParams<{ id: string }>()
  const id = decodeURIComponent(params.id)
  const [persona, setPersona] = useState<Persona | null>(null)
  const [name, setName] = useState("")
  const [summary, setSummary] = useState("")
  const [steps, setSteps] = useState("")
  const [error, setError] = useState("")

  function reload() {
    api<Persona>(`/api/personas/${encodeURIComponent(id)}`)
      .then(setPersona)
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
  }, [id])

  async function approve(itemId: string) {
    setError("")
    await api(`/api/items/${encodeURI(itemId)}/approve`, { method: "POST" })
    toast.success("Approved.")
    reload()
  }

  async function addSkill(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api(`/api/personas/${encodeURIComponent(id)}/skills`, {
      method: "POST",
      body: JSON.stringify({ name, summary, steps }),
    })
    setName("")
    setSummary("")
    setSteps("")
    toast.success("Draft skill saved.")
    reload()
  }

  return (
    <Shell>
      <ErrorAlert message={error} />
      {persona ? (
        <>
          <Card>
            <CardHeader>
              <Badge variant={persona.status === "stable" ? "secondary" : "outline"}>{persona.status}</Badge>
              <CardTitle className="text-2xl">{persona.title}</CardTitle>
              <CardDescription>{persona.summary}</CardDescription>
            </CardHeader>
            {persona.status !== "stable" ? (
              <CardFooter>
                <Button type="button" onClick={() => approve(persona.id).catch((exc: Error) => setError(exc.message))}>
                  Approve persona
                </Button>
              </CardFooter>
            ) : null}
          </Card>
          <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2 @5xl/main:grid-cols-3">
            {(persona.skills ?? []).map((skill: Skill) => (
              <Card key={skill.id}>
                <CardHeader>
                  <Badge variant={skill.status === "stable" ? "secondary" : "outline"}>{skill.status}</Badge>
                  <CardTitle>{skill.title}</CardTitle>
                  <CardDescription>{skill.summary}</CardDescription>
                </CardHeader>
                {skill.status !== "stable" ? (
                  <CardFooter>
                    <Button type="button" onClick={() => approve(skill.id).catch((exc: Error) => setError(exc.message))}>
                      Approve
                    </Button>
                  </CardFooter>
                ) : null}
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader>
              <CardTitle><h2>Add a skill</h2></CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={(event) => addSkill(event).catch((exc: Error) => setError(exc.message))}>
                <FieldGroup>
                  <Field>
                    <FieldLabel htmlFor="skill-name">Name</FieldLabel>
                    <Input id="skill-name" value={name} onChange={(event) => setName(event.target.value)} required />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="skill-summary">Summary</FieldLabel>
                    <Input id="skill-summary" value={summary} onChange={(event) => setSummary(event.target.value)} />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="skill-steps">Steps</FieldLabel>
                    <Textarea id="skill-steps" rows={5} value={steps} onChange={(event) => setSteps(event.target.value)} />
                  </Field>
                  <Button type="submit">Save draft skill</Button>
                </FieldGroup>
              </form>
            </CardContent>
          </Card>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Loading persona…</p>
      )}
    </Shell>
  )
}

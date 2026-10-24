"use client"

import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api, type Persona, type Skill } from "@/lib/api"
import { skillHref } from "@/lib/routes"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

export default function PersonaPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const id = decodeURIComponent(params.id)
  const [persona, setPersona] = useState<Persona | null>(null)
  const [title, setTitle] = useState("")
  const [summary, setSummary] = useState("")
  const [body, setBody] = useState("")
  const [name, setName] = useState("")
  const [skillSummary, setSkillSummary] = useState("")
  const [steps, setSteps] = useState("")
  const [error, setError] = useState("")

  function reload() {
    api<Persona>(`/api/personas/${encodeURIComponent(id)}`)
      .then((row) => {
        setPersona(row)
        setTitle(row.title)
        setSummary(row.summary)
        setBody(row.body)
      })
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
  }, [id])

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api(`/api/personas/${encodeURIComponent(id)}`, {
      method: "POST",
      body: JSON.stringify({ title, summary, body }),
    })
    toast.success("Persona updated.")
    reload()
  }

  async function approve(itemId: string) {
    setError("")
    await api(`/api/items/${encodeURI(itemId)}/approve`, { method: "POST" })
    toast.success("Approved.")
    reload()
  }

  async function remove() {
    setError("")
    await api(`/api/personas/${encodeURIComponent(id)}`, { method: "DELETE" })
    toast.success("Persona removed.")
    router.push("/personas")
  }

  async function addSkill(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api(`/api/personas/${encodeURIComponent(id)}/skills`, {
      method: "POST",
      body: JSON.stringify({ name, summary: skillSummary, steps }),
    })
    setName("")
    setSkillSummary("")
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
              <CardDescription>{persona.summary || "No summary yet."}</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={(event) => save(event).catch((exc: Error) => setError(exc.message))}>
                <FieldGroup>
                  <Field>
                    <FieldLabel htmlFor="title">Title</FieldLabel>
                    <Input id="title" value={title} onChange={(event) => setTitle(event.target.value)} required />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="summary">Summary</FieldLabel>
                    <Input id="summary" value={summary} onChange={(event) => setSummary(event.target.value)} />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="body">Rules</FieldLabel>
                    <Textarea id="body" rows={6} value={body} onChange={(event) => setBody(event.target.value)} />
                  </Field>
                  <div className="flex flex-wrap gap-2">
                    <Button type="submit">Save changes</Button>
                    {persona.status !== "stable" ? (
                      <Button type="button" variant="outline" onClick={() => approve(persona.id).catch((exc: Error) => setError(exc.message))}>
                        Approve persona
                      </Button>
                    ) : null}
                    <Button type="button" variant="destructive" onClick={() => remove().catch((exc: Error) => setError(exc.message))}>
                      Delete persona
                    </Button>
                  </div>
                </FieldGroup>
              </form>
            </CardContent>
          </Card>
          <section className="flex flex-col gap-3">
            <h2 className="text-base font-medium">Skills this persona uses</h2>
            {(persona.skills ?? []).length === 0 ? <p className="text-sm text-muted-foreground">No skills filed under this persona yet.</p> : null}
            <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
              {(persona.skills ?? []).map((skill: Skill) => (
                <Card key={skill.id}>
                  <CardHeader>
                    <Badge variant={skill.status === "stable" ? "secondary" : "outline"}>{skill.status}</Badge>
                    <CardTitle>
                      <Link href={skillHref(skill.id)} className="hover:underline">{skill.title}</Link>
                    </CardTitle>
                    <CardDescription>{skill.summary || "No summary yet."}</CardDescription>
                  </CardHeader>
                  <CardFooter className="gap-2">
                    <Button variant="outline" nativeButton={false} render={<Link href={skillHref(skill.id)} />}>Open skill</Button>
                    {skill.status !== "stable" ? (
                      <Button type="button" onClick={() => approve(skill.id).catch((exc: Error) => setError(exc.message))}>Approve</Button>
                    ) : null}
                  </CardFooter>
                </Card>
              ))}
            </div>
          </section>
          <Card>
            <CardHeader>
              <CardTitle><h2>Add a skill</h2></CardTitle>
              <CardDescription>New skills stay off until you approve them.</CardDescription>
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
                    <Input id="skill-summary" value={skillSummary} onChange={(event) => setSkillSummary(event.target.value)} />
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

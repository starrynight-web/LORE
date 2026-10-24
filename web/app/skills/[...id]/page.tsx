"use client"

import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api, type Skill } from "@/lib/api"
import { personaHref } from "@/lib/routes"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

export default function SkillPage() {
  const params = useParams<{ id: string[] }>()
  const router = useRouter()
  const id = (params.id ?? []).map((part) => decodeURIComponent(part)).join("/")
  const encoded = (params.id ?? []).map((part) => encodeURIComponent(part)).join("/")
  const [skill, setSkill] = useState<Skill | null>(null)
  const [title, setTitle] = useState("")
  const [summary, setSummary] = useState("")
  const [body, setBody] = useState("")
  const [error, setError] = useState("")

  function reload() {
    api<Skill>(`/api/skills/${encoded}`)
      .then((row) => {
        setSkill(row)
        setTitle(row.title)
        setSummary(row.summary)
        setBody(row.body)
      })
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
  }, [encoded])

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api(`/api/skills/${encoded}`, {
      method: "POST",
      body: JSON.stringify({ title, summary, body }),
    })
    toast.success("Skill updated.")
    reload()
  }

  async function approve() {
    setError("")
    await api(`/api/items/${encodeURI(id)}/approve`, { method: "POST" })
    toast.success("Skill approved.")
    reload()
  }

  async function remove() {
    setError("")
    await api(`/api/skills/${encoded}`, { method: "DELETE" })
    toast.success("Skill removed.")
    router.push("/skills")
  }

  return (
    <Shell>
      <ErrorAlert message={error} />
      {skill ? (
        <Card>
          <CardHeader>
            <Badge variant={skill.status === "stable" ? "secondary" : "outline"}>{skill.status}</Badge>
            <CardTitle className="text-2xl">{skill.title}</CardTitle>
            <CardDescription>
              {skill.persona ? (
                <>
                  Filed under <Link href={personaHref(skill.persona)} className="hover:underline">{skill.persona}</Link>
                </>
              ) : (
                "Not filed under a persona."
              )}
            </CardDescription>
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
                  <p className="text-xs text-muted-foreground">A short line the coding agent sees when it asks about this skill.</p>
                </Field>
                <Field>
                  <FieldLabel htmlFor="body">Steps</FieldLabel>
                  <Textarea id="body" rows={12} value={body} onChange={(event) => setBody(event.target.value)} />
                </Field>
                <div className="flex flex-wrap gap-2">
                  <Button type="submit">Save changes</Button>
                  {skill.status !== "stable" ? (
                    <Button type="button" variant="outline" onClick={() => approve().catch((exc: Error) => setError(exc.message))}>
                      Approve skill
                    </Button>
                  ) : null}
                  <Button type="button" variant="destructive" onClick={() => remove().catch((exc: Error) => setError(exc.message))}>
                    Delete skill
                  </Button>
                </div>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>
      ) : (
        <p className="text-sm text-muted-foreground">Loading skill…</p>
      )}
    </Shell>
  )
}

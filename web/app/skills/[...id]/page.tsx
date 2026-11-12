"use client"

import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { GovernanceBadges } from "@/components/governance-badges"
import { Shell } from "@/components/Shell"
import { api, ApiError, type GovernanceFinding, type Skill } from "@/lib/api"
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
  const [blockFindings, setBlockFindings] = useState<GovernanceFinding[]>([])
  const [acceptNote, setAcceptNote] = useState("")

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

  async function approve(acceptRisk = false) {
    setError("")
    try {
      await api(`/api/items/${encodeURI(id)}/approve`, {
        method: "POST",
        body: JSON.stringify(acceptRisk ? { accept_risk: true, note: acceptNote } : {}),
      })
      setBlockFindings([])
      setAcceptNote("")
      toast.success(acceptRisk ? "Skill approved with accepted risk." : "Skill approved.")
      reload()
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 409) {
        const gov = (exc.body.governance || {}) as { scan?: { findings?: GovernanceFinding[] } }
        setBlockFindings(gov.scan?.findings || [])
        setError(exc.message)
        return
      }
      throw exc
    }
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
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={skill.status === "stable" ? "secondary" : "outline"}>{skill.status}</Badge>
              <GovernanceBadges governance={skill.governance} />
            </div>
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
            {blockFindings.length > 0 ? (
              <div className="mb-4 space-y-2 rounded-md border border-destructive/40 p-3 text-sm">
                <p className="font-medium">Approve blocked by security findings</p>
                <ul className="list-disc space-y-1 pl-5">
                  {blockFindings.map((finding) => (
                    <li key={`${finding.id}-${finding.evidence?.join(",") || ""}`}>
                      <span className="font-medium">[{finding.severity}]</span> {finding.id}: {finding.title}
                      {finding.evidence?.length ? ` (${finding.evidence.join(", ")})` : ""}
                    </li>
                  ))}
                </ul>
                <Field>
                  <FieldLabel htmlFor="accept-note">Note for accept risk</FieldLabel>
                  <Input id="accept-note" value={acceptNote} onChange={(event) => setAcceptNote(event.target.value)} placeholder="Why this risk is accepted" />
                </Field>
                <Button type="button" variant="destructive" onClick={() => approve(true).catch((exc: Error) => setError(exc.message))}>
                  Approve anyway
                </Button>
              </div>
            ) : null}
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
                    <Button type="button" variant="outline" onClick={() => approve(false).catch((exc: Error) => setError(exc.message))}>
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

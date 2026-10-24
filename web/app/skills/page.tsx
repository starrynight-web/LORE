"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Onboarding } from "@/components/onboarding"
import { Shell } from "@/components/Shell"
import { api, type Persona, type Skill, type WaitingSkill } from "@/lib/api"
import { personaHref, skillHref } from "@/lib/routes"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [waiting, setWaiting] = useState<WaitingSkill[]>([])
  const [personas, setPersonas] = useState<Persona[]>([])
  const [error, setError] = useState("")
  const [addOpen, setAddOpen] = useState(false)
  const [accepting, setAccepting] = useState<WaitingSkill | null>(null)

  function reload() {
    api<{ skills: Skill[]; waiting: WaitingSkill[] }>("/api/skills")
      .then((row) => {
        setSkills(row.skills)
        setWaiting(row.waiting)
      })
      .catch((exc: Error) => setError(exc.message))
    api<{ personas: Persona[] }>("/api/personas")
      .then((row) => setPersonas(row.personas))
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
  }, [])

  async function removeWaiting(skillId: string) {
    setError("")
    await api(`/api/inbox/${encodeURIComponent(skillId)}`, { method: "DELETE" })
    reload()
  }

  async function remove(skillId: string) {
    setError("")
    await api(`/api/skills/${skillId.split("/").map(encodeURIComponent).join("/")}`, { method: "DELETE" })
    toast.success("Skill removed.")
    reload()
  }

  return (
    <Shell>
      <ErrorAlert message={error} />
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-medium">Skills</h2>
          <p className="text-sm text-muted-foreground">Instructions a role can hand to your coding agent.</p>
        </div>
        <Button type="button" size="sm" onClick={() => setAddOpen(true)}>
          Add skill
        </Button>
      </div>
      {waiting.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-base font-medium">Waiting for a role</h2>
          <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
            {waiting.map((skill) => (
              <Card key={skill.id}>
                <CardHeader>
                  <Badge variant="outline">waiting</Badge>
                  <CardTitle>{skill.title}</CardTitle>
                  <CardDescription>{skill.summary || "No summary yet."}</CardDescription>
                </CardHeader>
                <CardFooter className="gap-2">
                  <Button type="button" onClick={() => setAccepting(skill)}>
                    Choose a role
                  </Button>
                  <Button type="button" variant="destructive" onClick={() => removeWaiting(skill.id).catch((exc: Error) => setError(exc.message))}>
                    Delete
                  </Button>
                </CardFooter>
              </Card>
            ))}
          </div>
        </section>
      ) : null}
      <section className="flex flex-col gap-3">
        <h2 className="text-base font-medium">Saved skills</h2>
        {skills.length === 0 ? <p className="text-sm text-muted-foreground">No skills are filed under a role yet.</p> : null}
        <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
          {skills.map((skill) => (
            <Card key={skill.id}>
              <CardHeader>
                <Badge variant={skill.status === "stable" ? "secondary" : "outline"}>{skill.status === "stable" ? "ready" : "draft"}</Badge>
                <CardTitle>
                  <Link href={skillHref(skill.id)} className="hover:underline">{skill.title}</Link>
                </CardTitle>
                <CardDescription>{skill.summary || "No summary yet."}</CardDescription>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                {skill.persona ? <Link href={personaHref(skill.persona)} className="hover:underline">{skill.persona.replace(/^persona:/, "")}</Link> : "No role yet"}
              </CardContent>
              <CardFooter className="gap-2">
                <Button variant="outline" nativeButton={false} render={<Link href={skillHref(skill.id)} />}>Open</Button>
                <Button type="button" variant="destructive" onClick={() => remove(skill.id).catch((exc: Error) => setError(exc.message))}>
                  Delete
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </section>
      {addOpen ? (
        <Onboarding
          panel="skills"
          initial={{ completed: true, step: "done" }}
          onDone={() => {
            setAddOpen(false)
            reload()
          }}
          onClose={() => {
            setAddOpen(false)
            reload()
          }}
        />
      ) : null}
      {accepting ? (
        <RoleDialog
          skill={accepting}
          personas={personas}
          onClose={() => setAccepting(null)}
          onDone={() => {
            setAccepting(null)
            toast.success("Skill filed under that role.")
            reload()
          }}
          onError={(message) => setError(message)}
        />
      ) : null}
    </Shell>
  )
}

function RoleDialog({
  skill,
  personas,
  onClose,
  onDone,
  onError,
}: {
  skill: WaitingSkill
  personas: Persona[]
  onClose: () => void
  onDone: () => void
  onError: (message: string) => void
}) {
  const [persona, setPersona] = useState(personas[0]?.id ?? "")
  const [name, setName] = useState("")
  const [busy, setBusy] = useState(false)
  const items = personas.map((item) => ({ label: item.title, value: item.id }))

  async function accept(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      let chosen = persona
      const fresh = name.trim()
      if (fresh) {
        const created = await api<Persona>("/api/personas", {
          method: "POST",
          body: JSON.stringify({ name: fresh, summary: "", steps: "" }),
        })
        chosen = created.id
      }
      if (!chosen) {
        onError("Choose a role for this skill, or name a new one.")
        return
      }
      await api(`/api/inbox/${encodeURIComponent(skill.id)}/adopt`, {
        method: "POST",
        body: JSON.stringify({ persona: chosen }),
      })
      onDone()
    } catch (exc) {
      onError(exc instanceof Error ? exc.message : "The skill could not be filed.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/70 p-4 backdrop-blur-md">
      <div role="dialog" aria-modal="true" aria-labelledby="role-title" className="w-full max-w-md rounded-xl border bg-card p-6 shadow-lg">
        <form className="flex flex-col gap-4" onSubmit={(event) => accept(event)}>
          <div>
            <h2 id="role-title" className="text-lg font-medium">Which role should use this skill?</h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              {skill.title} is waiting. Pick a role, or name a new one.
            </p>
          </div>
          {items.length > 0 ? (
            <Field>
              <FieldLabel htmlFor="accept-persona">Role</FieldLabel>
              <Select items={items} value={persona} onValueChange={(value) => value && setPersona(value)}>
                <SelectTrigger id="accept-persona" className="w-full">
                  <SelectValue placeholder="Choose a role" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {items.map((item) => (
                      <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          ) : (
            <p className="text-sm text-muted-foreground">You have not created a role yet. Name one and this skill will go there.</p>
          )}
          <Field>
            <FieldLabel htmlFor="accept-name">{items.length > 0 ? "Or create a role" : "Role name"}</FieldLabel>
            <Input id="accept-name" value={name} onChange={(event) => setName(event.target.value)} required={items.length === 0} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Adding…" : "Add to this role"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

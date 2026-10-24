"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api, type Persona, type RegistrySkill, type Skill, type WaitingSkill } from "@/lib/api"
import { personaHref, skillHref } from "@/lib/routes"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [waiting, setWaiting] = useState<WaitingSkill[]>([])
  const [personas, setPersonas] = useState<Persona[]>([])
  const [persona, setPersona] = useState("")
  const [name, setName] = useState("")
  const [summary, setSummary] = useState("")
  const [steps, setSteps] = useState("")
  const [query, setQuery] = useState("")
  const [found, setFound] = useState<RegistrySkill[]>([])
  const [error, setError] = useState("")

  function reload() {
    api<{ skills: Skill[]; waiting: WaitingSkill[] }>("/api/skills")
      .then((row) => {
        setSkills(row.skills)
        setWaiting(row.waiting)
      })
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
    api<{ personas: Persona[] }>("/api/personas")
      .then((row) => {
        setPersonas(row.personas)
        if (row.personas[0]) setPersona(row.personas[0].id)
      })
      .catch((exc: Error) => setError(exc.message))
  }, [])

  async function create(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api("/api/skills", {
      method: "POST",
      body: JSON.stringify({ persona, name, summary, steps }),
    })
    setName("")
    setSummary("")
    setSteps("")
    toast.success("Draft skill saved.")
    reload()
  }

  async function search(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    const row = await api<{ skills: RegistrySkill[] }>("/api/skills/search", {
      method: "POST",
      body: JSON.stringify({ query }),
    })
    setFound(row.skills)
  }

  async function addRegistry(skill: RegistrySkill) {
    setError("")
    await api("/api/skills/add", {
      method: "POST",
      body: JSON.stringify({ source: skill.source, skill_id: skill.skill_id }),
    })
    toast.success("Skill added. File it under a persona below.")
    reload()
  }

  async function addFile(file: File) {
    setError("")
    const content = await file.text()
    await api("/api/inbox", { method: "POST", body: JSON.stringify({ name: file.name, content }) })
    toast.success("Skill file added.")
    reload()
  }

  async function adopt(skillId: string) {
    setError("")
    await api(`/api/inbox/${encodeURIComponent(skillId)}/adopt`, {
      method: "POST",
      body: JSON.stringify({ persona }),
    })
    toast.success("Skill filed under the persona.")
    reload()
  }

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

  const personaItems = personas.map((item) => ({ label: item.title, value: item.id }))

  return (
    <Shell>
      <ErrorAlert message={error} />
      <Card>
        <CardHeader>
          <CardTitle><h2>Add a skill</h2></CardTitle>
          <CardDescription>Search skills.sh, add a markdown file, or write the steps yourself under a persona.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          <form className="flex gap-2" onSubmit={(event) => search(event).catch((exc: Error) => setError(exc.message))}>
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search skills.sh" aria-label="Search skills.sh" />
            <Button type="submit">Search</Button>
          </form>
          {found.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {found.map((skill) => (
                <li key={`${skill.source}/${skill.skill_id}`} className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{skill.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">{skill.source}</span>
                  </span>
                  <Button type="button" size="sm" onClick={() => addRegistry(skill).catch((exc: Error) => setError(exc.message))}>Add</Button>
                </li>
              ))}
            </ul>
          ) : null}
          <Field>
            <FieldLabel htmlFor="local-skill">Markdown file</FieldLabel>
            <Input
              id="local-skill"
              type="file"
              accept=".md,text/markdown,text/plain"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) addFile(file).catch((exc: Error) => setError(exc.message))
                event.target.value = ""
              }}
            />
          </Field>
          <form onSubmit={(event) => create(event).catch((exc: Error) => setError(exc.message))}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="skill-persona">Persona</FieldLabel>
                <Select items={personaItems} value={persona} onValueChange={(value) => value && setPersona(value)} disabled={personaItems.length === 0}>
                  <SelectTrigger id="skill-persona" className="w-full">
                    <SelectValue placeholder="Create a persona first" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {personaItems.map((item) => (
                        <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
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
                <Textarea id="skill-steps" rows={4} value={steps} onChange={(event) => setSteps(event.target.value)} />
              </Field>
              <Button type="submit" disabled={!persona}>Save draft skill</Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
      {waiting.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-base font-medium">Waiting for a persona</h2>
          <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
            {waiting.map((skill) => (
              <Card key={skill.id}>
                <CardHeader>
                  <Badge variant="outline">waiting</Badge>
                  <CardTitle>{skill.title}</CardTitle>
                  <CardDescription>{skill.summary || skill.source || "No summary yet."}</CardDescription>
                </CardHeader>
                <CardFooter className="gap-2">
                  <Button type="button" disabled={!persona} onClick={() => adopt(skill.id).catch((exc: Error) => setError(exc.message))}>
                    File under selected persona
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
        <h2 className="text-base font-medium">Configured skills</h2>
        {skills.length === 0 ? <p className="text-sm text-muted-foreground">No skills are filed under a persona yet.</p> : null}
        <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
          {skills.map((skill) => (
            <Card key={skill.id}>
              <CardHeader>
                <Badge variant={skill.status === "stable" ? "secondary" : "outline"}>{skill.status}</Badge>
                <CardTitle>
                  <Link href={skillHref(skill.id)} className="hover:underline">{skill.title}</Link>
                </CardTitle>
                <CardDescription>{skill.summary || "No summary yet."}</CardDescription>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                {skill.persona ? <Link href={personaHref(skill.persona)} className="hover:underline">{skill.persona}</Link> : "No persona"}
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
    </Shell>
  )
}

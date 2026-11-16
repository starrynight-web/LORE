"use client"

import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/confirm-dialog"
import { ErrorAlert } from "@/components/error-alert"
import { GovernanceBadges } from "@/components/governance-badges"
import { Shell } from "@/components/Shell"
import { api, ApiError, type GovernanceFinding, type Persona, type Skill } from "@/lib/api"
import { skillHref } from "@/lib/routes"
import { SKILL_SORT_OPTIONS, sortBySkillOption, statusLabel, type SkillSort } from "@/lib/sort"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
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
  const [blockFindings, setBlockFindings] = useState<GovernanceFinding[]>([])
  const [blockedItem, setBlockedItem] = useState("")
  const [acceptNote, setAcceptNote] = useState("")
  const [skillFilter, setSkillFilter] = useState("")
  const [skillSort, setSkillSort] = useState<SkillSort>("status")
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

  function reload() {
    api<Persona>(`/api/personas/${encodeURIComponent(id)}`)
      .then((row) => {
        setPersona(row)
        setTitle(row.title)
        setSummary(row.summary)
        setBody(row.body)
        setSelected((current) => {
          const ids = new Set((row.skills ?? []).map((skill) => skill.id))
          return new Set([...current].filter((item) => ids.has(item)))
        })
      })
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
  }, [id])

  const visibleSkills = useMemo(() => {
    const needle = skillFilter.trim().toLowerCase()
    const filtered = (persona?.skills ?? []).filter((skill) => {
      if (!needle) return true
      return (
        skill.title.toLowerCase().includes(needle) ||
        (skill.summary || "").toLowerCase().includes(needle)
      )
    })
    return sortBySkillOption(filtered, skillSort)
  }, [persona, skillFilter, skillSort])

  const draftSkills = visibleSkills.filter((skill) => skill.status !== "stable")
  const selectedDrafts = draftSkills.filter((skill) => selected.has(skill.id))

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

  async function approve(itemId: string, acceptRisk = false) {
    setError("")
    try {
      await api(`/api/items/${encodeURI(itemId)}/approve`, {
        method: "POST",
        body: JSON.stringify(acceptRisk ? { accept_risk: true, note: acceptNote } : {}),
      })
      setBlockFindings([])
      setBlockedItem("")
      setAcceptNote("")
      toast.success(acceptRisk ? "Approved with accepted risk." : "Approved.")
      reload()
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 409) {
        const gov = (exc.body.governance || {}) as { scan?: { findings?: GovernanceFinding[] } }
        setBlockedItem(itemId)
        setBlockFindings(gov.scan?.findings || [])
        setError(exc.message)
        return
      }
      throw exc
    }
  }

  async function approveSelected() {
    if (selectedDrafts.length === 0) return
    setBulkBusy(true)
    setError("")
    let ok = 0
    try {
      for (const skill of selectedDrafts) {
        try {
          await api(`/api/items/${encodeURI(skill.id)}/approve`, {
            method: "POST",
            body: JSON.stringify({}),
          })
          ok += 1
          setSelected((current) => {
            const next = new Set(current)
            next.delete(skill.id)
            return next
          })
        } catch (exc) {
          if (exc instanceof ApiError && exc.status === 409) {
            const gov = (exc.body.governance || {}) as { scan?: { findings?: GovernanceFinding[] } }
            setBlockedItem(skill.id)
            setBlockFindings(gov.scan?.findings || [])
            setError(exc.message)
            if (ok > 0) toast.success(`Approved ${ok} skill${ok === 1 ? "" : "s"} before a block.`)
            reload()
            return
          }
          throw exc
        }
      }
      toast.success(`Approved ${ok} skill${ok === 1 ? "" : "s"}.`)
      reload()
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Bulk approve failed.")
      reload()
    } finally {
      setBulkBusy(false)
    }
  }

  function toggleSkill(skillId: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current)
      if (checked) next.add(skillId)
      else next.delete(skillId)
      return next
    })
  }

  function selectAllDrafts() {
    setSelected(new Set(draftSkills.map((skill) => skill.id)))
  }

  function clearSelection() {
    setSelected(new Set())
  }

  async function remove() {
    setError("")
    setDeleting(true)
    try {
      await api(`/api/personas/${encodeURIComponent(id)}`, { method: "DELETE" })
      setConfirmDelete(false)
      toast.success("Persona removed. Its skills are waiting for a new role.")
      router.push("/personas")
    } finally {
      setDeleting(false)
    }
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
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={persona.status === "stable" ? "secondary" : "outline"}>{statusLabel(persona.status)}</Badge>
                <GovernanceBadges governance={persona.governance} />
              </div>
              <CardTitle className="text-2xl">{persona.title}</CardTitle>
              <CardDescription>{persona.summary || "No summary yet."}</CardDescription>
            </CardHeader>
            <CardContent>
              {blockFindings.length > 0 ? (
                <div className="mb-4 space-y-2 rounded-md border border-destructive/40 p-3 text-sm">
                  <p className="font-medium">Approve blocked for {blockedItem}</p>
                  <ul className="list-disc space-y-1 pl-5">
                    {blockFindings.map((finding) => (
                      <li key={`${finding.id}-${finding.evidence?.join(",") || ""}`}>
                        <span className="font-medium">[{finding.severity}]</span> {finding.id}: {finding.title}
                      </li>
                    ))}
                  </ul>
                  <Field>
                    <FieldLabel htmlFor="accept-note">Note for accept risk</FieldLabel>
                    <Input id="accept-note" value={acceptNote} onChange={(event) => setAcceptNote(event.target.value)} />
                  </Field>
                  <Button type="button" variant="destructive" onClick={() => approve(blockedItem, true).catch((exc: Error) => setError(exc.message))}>
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
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="body">Rules</FieldLabel>
                    <FieldDescription>
                      Short paragraphs and bullet lines are easier to skim before the agent uses them.
                    </FieldDescription>
                    <Textarea
                      id="body"
                      rows={12}
                      value={body}
                      onChange={(event) => setBody(event.target.value)}
                      className="min-h-48 text-sm leading-7 whitespace-pre-wrap"
                      placeholder={"How this role should work:\n\n- Prefer…\n- Avoid…\n- When stuck…"}
                    />
                  </Field>
                  <div className="flex flex-wrap gap-2">
                    <Button type="submit">Save changes</Button>
                    {persona.status !== "stable" ? (
                      <Button type="button" variant="outline" onClick={() => approve(persona.id).catch((exc: Error) => setError(exc.message))}>
                        Approve persona
                      </Button>
                    ) : null}
                    <Button type="button" variant="destructive" onClick={() => setConfirmDelete(true)}>
                      Delete persona
                    </Button>
                  </div>
                </FieldGroup>
              </form>
            </CardContent>
          </Card>
          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-base font-medium">Skills this persona uses</h2>
                <p className="text-sm text-muted-foreground">Select drafts to approve several at once.</p>
              </div>
              {(persona.skills ?? []).length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="outline" size="sm" onClick={selectAllDrafts} disabled={draftSkills.length === 0}>
                    Select drafts
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={clearSelection} disabled={selected.size === 0}>
                    Clear
                  </Button>
                  <Button type="button" size="sm" onClick={() => approveSelected().catch((exc: Error) => setError(exc.message))} disabled={bulkBusy || selectedDrafts.length === 0}>
                    {bulkBusy ? "Approving…" : `Approve selected (${selectedDrafts.length})`}
                  </Button>
                </div>
              ) : null}
            </div>
            {(persona.skills ?? []).length === 0 ? <p className="text-sm text-muted-foreground">No skills filed under this persona yet.</p> : null}
            {(persona.skills ?? []).length > 0 ? (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <div className="max-w-md flex-1">
                  <Input
                    value={skillFilter}
                    onChange={(event) => setSkillFilter(event.target.value)}
                    placeholder="Search skills"
                    aria-label="Search skills for this persona"
                  />
                </div>
                <Field className="w-full sm:w-48">
                  <FieldLabel htmlFor="persona-skill-sort">Sort</FieldLabel>
                  <Select
                    items={SKILL_SORT_OPTIONS}
                    value={skillSort}
                    onValueChange={(value) => {
                      if (value === "name-asc" || value === "name-desc" || value === "status") setSkillSort(value)
                    }}
                  >
                    <SelectTrigger id="persona-skill-sort" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {SKILL_SORT_OPTIONS.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </Field>
              </div>
            ) : null}
            <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
              {visibleSkills.map((skill: Skill) => {
                const draft = skill.status !== "stable"
                const checked = selected.has(skill.id)
                return (
                  <Card key={skill.id}>
                    <CardHeader>
                      <div className="flex items-start gap-3">
                        {draft ? (
                          <input
                            type="checkbox"
                            className="mt-1 size-4 accent-foreground"
                            checked={checked}
                            onChange={(event) => toggleSkill(skill.id, event.target.checked)}
                            aria-label={`Select ${skill.title}`}
                          />
                        ) : (
                          <span className="mt-1 size-4" aria-hidden />
                        )}
                        <div className="min-w-0 flex-1">
                          <p className="text-xs text-muted-foreground">{statusLabel(skill.status)}</p>
                          <CardTitle>
                            <Link href={skillHref(skill.id)} className="hover:underline">{skill.title}</Link>
                          </CardTitle>
                          <CardDescription className="line-clamp-2">{skill.summary || "No summary yet."}</CardDescription>
                        </div>
                      </div>
                    </CardHeader>
                    <CardFooter className="gap-2">
                      <Button variant="outline" nativeButton={false} render={<Link href={skillHref(skill.id)} />}>Open skill</Button>
                      {draft ? (
                        <Button type="button" onClick={() => approve(skill.id).catch((exc: Error) => setError(exc.message))}>Approve</Button>
                      ) : null}
                    </CardFooter>
                  </Card>
                )
              })}
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
      {confirmDelete && persona ? (
        <ConfirmDialog
          title={`Delete ${persona.title}?`}
          description={
            (persona.skills ?? []).length > 0
              ? `This removes the role. Its ${(persona.skills ?? []).length} skill${(persona.skills ?? []).length === 1 ? "" : "s"} will go back to waiting so you can attach ${(persona.skills ?? []).length === 1 ? "it" : "them"} to another role.`
              : "This removes the role. You can create a new one later."
          }
          confirmLabel="Delete persona"
          busy={deleting}
          onCancel={() => {
            if (!deleting) setConfirmDelete(false)
          }}
          onConfirm={() => remove().catch((exc: Error) => setError(exc.message))}
        />
      ) : null}
    </Shell>
  )
}

"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { ArrowUpRightIcon, CheckIcon, SearchIcon, Trash2Icon } from "lucide-react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Onboarding } from "@/components/onboarding"
import { PageHero } from "@/components/page-hero"
import { Shell } from "@/components/Shell"
import { api, type Persona, type Skill, type WaitingSkill } from "@/lib/api"
import { personaHref, skillHref } from "@/lib/routes"
import { SKILL_SORT_OPTIONS, sortBySkillOption, statusLabel, type SkillSort } from "@/lib/sort"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
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

function matchesQuery(title: string, summary: string, query: string) {
  const needle = query.trim().toLowerCase()
  if (!needle) return true
  return title.toLowerCase().includes(needle) || summary.toLowerCase().includes(needle)
}

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [waiting, setWaiting] = useState<WaitingSkill[]>([])
  const [personas, setPersonas] = useState<Persona[]>([])
  const [error, setError] = useState("")
  const [addOpen, setAddOpen] = useState(false)
  const [accepting, setAccepting] = useState<WaitingSkill | null>(null)
  const [filter, setFilter] = useState("")
  const [sort, setSort] = useState<SkillSort>("name-asc")

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

  const visibleWaiting = waiting.filter((skill) => matchesQuery(skill.title, skill.summary || "", filter))
  const visibleSkills = useMemo(
    () =>
      sortBySkillOption(
        skills.filter((skill) => matchesQuery(skill.title, skill.summary || "", filter)),
        sort,
      ),
    [skills, filter, sort],
  )

  return (
    <Shell>
      <ErrorAlert message={error} />
      <PageHero
        title="Skills"
        subtitle="Instructions a role can hand to your coding agent."
        action={
          <Button type="button" onClick={() => setAddOpen(true)}>
            + Add skill
          </Button>
        }
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative max-w-md flex-1">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Search saved skills..."
            aria-label="Search saved skills"
            className="h-10 rounded-full bg-card pl-10"
          />
        </div>
        <div className="w-full sm:w-48">
          <Select
            items={SKILL_SORT_OPTIONS}
            value={sort}
            onValueChange={(value) => {
              if (value === "name-asc" || value === "name-desc" || value === "status") setSort(value)
            }}
          >
            <SelectTrigger id="skill-sort" aria-label="Sort skills" className="h-10 w-full rounded-full bg-card px-4">
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
        </div>
      </div>

      {waiting.length > 0 ? (
        <section className="flex flex-col gap-3">
          <div>
            <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Waiting for a role</h2>
            <p className="text-[12.5px] text-muted-foreground">Inbox skills ready to be filed under a persona.</p>
          </div>
          {visibleWaiting.length === 0 ? (
            <Card className="p-6 text-sm text-muted-foreground">No waiting skills match that search.</Card>
          ) : null}
          <div className="grid grid-cols-1 gap-[18px] md:grid-cols-2 lg:grid-cols-3">
            {visibleWaiting.map((skill) => (
              <Card key={skill.id} className="flex flex-col justify-between gap-4 px-[22px] py-5">
                <div>
                  <span className="inline-flex rounded-full bg-[#a59bf3]/25 px-2.5 py-0.5 text-[11px] font-semibold text-foreground">
                    inbox
                  </span>
                  <h3 className="mt-2.5 truncate text-[16px] font-semibold tracking-[-0.01em]">{skill.title}</h3>
                  <p className="mt-1 line-clamp-2 text-[12.5px] text-muted-foreground">
                    {skill.summary || "No summary yet."}
                  </p>
                </div>
                <div className="flex items-center justify-between border-t border-border pt-3">
                  <button
                    type="button"
                    onClick={() => removeWaiting(skill.id).catch((exc: Error) => setError(exc.message))}
                    aria-label={`Delete ${skill.title}`}
                    className="grid size-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2Icon className="size-4" />
                  </button>
                  <Button type="button" size="sm" onClick={() => setAccepting(skill)}>
                    Choose a role
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </section>
      ) : null}

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Saved skills</h2>
          <p className="text-[12.5px] text-muted-foreground">Skills filed under personas and ready for review.</p>
        </div>
        {skills.length === 0 ? (
          <Card className="p-6 text-sm text-muted-foreground">No skills are filed under a role yet.</Card>
        ) : null}
        {skills.length > 0 && visibleSkills.length === 0 ? (
          <Card className="p-6 text-sm text-muted-foreground">No saved skills match that search.</Card>
        ) : null}
        <div className="grid grid-cols-1 gap-[18px] md:grid-cols-2 lg:grid-cols-3">
          {visibleSkills.map((skill) => {
            const isStable = skill.status === "stable"
            return (
              <Card key={skill.id} className="flex flex-col justify-between gap-4 px-[22px] py-5">
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold",
                        isStable
                          ? "bg-[var(--lore-sage)] text-[#1a2e1c]"
                          : "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                      )}
                    >
                      {isStable ? <CheckIcon className="size-3" /> : null}
                      {statusLabel(skill.status)}
                    </span>
                    {skill.persona ? (
                      <Link
                        href={personaHref(skill.persona)}
                        className="truncate rounded-full bg-muted px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground hover:text-foreground"
                      >
                        {skill.persona.replace(/^persona:/, "")}
                      </Link>
                    ) : null}
                  </div>
                  <h3 className="mt-2.5 truncate text-[16px] font-semibold tracking-[-0.01em]">
                    <Link href={skillHref(skill.id)} className="hover:underline">
                      {skill.title}
                    </Link>
                  </h3>
                  <p className="mt-1 line-clamp-2 text-[12.5px] text-muted-foreground">
                    {skill.summary || "No summary yet."}
                  </p>
                </div>

                <div className="flex items-center justify-between border-t border-border pt-3">
                  <button
                    type="button"
                    onClick={() => remove(skill.id).catch((exc: Error) => setError(exc.message))}
                    aria-label={`Delete ${skill.title}`}
                    className="grid size-8 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2Icon className="size-4" />
                  </button>
                  <Link
                    href={skillHref(skill.id)}
                    className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-semibold text-foreground transition-colors hover:bg-muted"
                  >
                    Open
                    <ArrowUpRightIcon className="size-3.5" />
                  </Link>
                </div>
              </Card>
            )
          })}
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

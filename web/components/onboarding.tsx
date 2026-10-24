"use client"

import { useEffect, useId, useRef, useState } from "react"

import { FolderPicker } from "@/components/folder-picker"
import { ErrorAlert } from "@/components/error-alert"
import { Button } from "@/components/ui/button"
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
import { api, type Onboarding, type RegistrySkill, type WaitingSkill } from "@/lib/api"
import { PROVIDERS, defaultModels } from "@/lib/providers"

const ORDER = ["welcome", "skills", "persona", "codebase"] as const

function installs(value: number) {
  if (value >= 1000) return `${Math.round(value / 1000)}k installs`
  return `${value} installs`
}

function registryKey(skill: RegistrySkill) {
  return `${skill.source}/${skill.skill_id}`
}

export function Onboarding({
  initial,
  onDone,
}: {
  initial: Onboarding
  onDone: () => void
}) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const [step, setStep] = useState(initial.step === "done" ? "welcome" : initial.step)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [featured, setFeatured] = useState<RegistrySkill[]>([])
  const [results, setResults] = useState<RegistrySkill[] | null>(null)
  const [query, setQuery] = useState("")
  const [picked, setPicked] = useState<RegistrySkill[]>([])
  const [waiting, setWaiting] = useState<WaitingSkill[]>([])
  const [chosenSkills, setChosenSkills] = useState<string[]>([])
  const [mode, setMode] = useState<"write" | "model">("write")
  const [provider, setProvider] = useState("groq")
  const [apiKey, setApiKey] = useState("")
  const [models, setModels] = useState<string[]>(defaultModels("groq"))
  const [model, setModel] = useState(defaultModels("groq")[0])
  const [name, setName] = useState("")
  const [summary, setSummary] = useState("")
  const [rules, setRules] = useState("")
  const [note, setNote] = useState("")
  const [codeName, setCodeName] = useState("")
  const [codePath, setCodePath] = useState("")
  const [savedPersona, setSavedPersona] = useState(false)

  const index = Math.max(0, ORDER.indexOf(step as (typeof ORDER)[number]))
  const shown = results ?? featured

  useEffect(() => {
    const node = panel.current
    const focusable = node?.querySelector<HTMLElement>("button, input, textarea, select, [href]")
    focusable?.focus()
  }, [step])

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault()
        event.stopPropagation()
        return
      }
      if (event.key !== "Tab" || !panel.current) return
      const items = [...panel.current.querySelectorAll<HTMLElement>("button, input, textarea, select, a[href], [tabindex='0']")].filter(
        (item) => !item.hasAttribute("disabled"),
      )
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", onKey, true)
    return () => document.removeEventListener("keydown", onKey, true)
  }, [])

  useEffect(() => {
    if (step !== "skills") return
    api<{ skills: RegistrySkill[] }>("/api/skills/featured")
      .then((row) => setFeatured(row.skills))
      .catch((exc: Error) => setError(exc.message))
    api<{ skills: WaitingSkill[] }>("/api/inbox")
      .then((row) => setWaiting(row.skills))
      .catch((exc: Error) => setError(exc.message))
  }, [step])

  useEffect(() => {
    if (step !== "persona") return
    api<{ skills: WaitingSkill[] }>("/api/inbox")
      .then((row) => {
        setWaiting(row.skills)
        setChosenSkills(row.skills.map((skill) => skill.id))
      })
      .catch((exc: Error) => setError(exc.message))
  }, [step])

  async function persist(next: string, completed = false) {
    await api<Onboarding>("/api/onboarding", {
      method: "POST",
      body: JSON.stringify({ step: completed ? "done" : next, completed }),
    })
    if (completed) onDone()
    else setStep(next)
  }

  async function go(next: string) {
    setError("")
    setBusy(true)
    try {
      await persist(next)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The setup site could not complete that.")
    } finally {
      setBusy(false)
    }
  }

  function toggleRegistry(skill: RegistrySkill) {
    setPicked((current) => {
      const key = registryKey(skill)
      if (current.some((item) => registryKey(item) === key)) {
        return current.filter((item) => registryKey(item) !== key)
      }
      return [...current, skill]
    })
  }

  async function search(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    const row = await api<{ skills: RegistrySkill[] }>("/api/skills/search", {
      method: "POST",
      body: JSON.stringify({ query }),
    })
    setResults(row.skills)
  }

  async function addFile(file: File) {
    setError("")
    const content = await file.text()
    const saved = await api<WaitingSkill>("/api/inbox", {
      method: "POST",
      body: JSON.stringify({ name: file.name, content }),
    })
    setWaiting((current) => [...current.filter((item) => item.id !== saved.id), saved])
  }

  async function continueSkills() {
    setError("")
    setBusy(true)
    try {
      for (const skill of picked) {
        await api("/api/skills/add", {
          method: "POST",
          body: JSON.stringify({ source: skill.source, skill_id: skill.skill_id }),
        })
      }
      await persist("persona")
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The setup site could not complete that.")
    } finally {
      setBusy(false)
    }
  }

  async function saveKey() {
    setError("")
    await api("/api/provider", {
      method: "POST",
      body: JSON.stringify({ provider, key: apiKey }),
    })
    const list = await api<{ model: string; models: string[] }>("/api/provider/models")
    const catalog = list.models.length > 0 ? list.models : list.model ? [list.model] : defaultModels(provider)
    const picked = model
    let chosen = list.model || catalog[0] || ""
    if (picked && picked !== chosen && catalog.includes(picked)) {
      await api("/api/provider/models", { method: "POST", body: JSON.stringify({ model: picked }) })
      chosen = picked
    }
    setModels(catalog)
    setModel(chosen)
    setApiKey("")
  }

  async function draft() {
    setError("")
    if (model) {
      await api("/api/provider/models", { method: "POST", body: JSON.stringify({ model }) })
    }
    const drafted = await api<{ title: string; summary: string; rules: string }>("/api/provider/draft", {
      method: "POST",
      body: JSON.stringify({ note, skill_ids: chosenSkills }),
    })
    setName(drafted.title)
    setSummary(drafted.summary)
    setRules(drafted.rules)
  }

  async function savePersona(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api("/api/personas", {
      method: "POST",
      body: JSON.stringify({ name, summary, steps: rules, skill_ids: chosenSkills }),
    })
    setSavedPersona(true)
    setName("")
    setSummary("")
    setRules("")
    setNote("")
  }

  async function mapCode() {
    setError("")
    setBusy(true)
    try {
      const created = await api<{ id: string }>("/api/codebases", {
        method: "POST",
        body: JSON.stringify({ name: codeName || "Codebase", path: codePath }),
      })
      await api(`/api/codebases/${encodeURIComponent(created.id)}`, {
        method: "POST",
        body: JSON.stringify({ build: true }),
      })
      await persist("done", true)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The setup site could not complete that.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/70 p-4 backdrop-blur-md">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex max-h-[min(44rem,calc(100vh-2rem))] w-full max-w-2xl flex-col overflow-hidden rounded-xl border bg-card text-card-foreground shadow-lg"
      >
        <div className="flex items-center justify-between border-b px-6 py-4">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {step === "welcome" ? "Welcome" : `Step ${index + 1} of ${ORDER.length}`}
          </p>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-5">
          <ErrorAlert message={error} />
          {step === "welcome" ? (
            <div className="flex flex-col gap-3 py-4">
              <h2 id={titleId} className="text-3xl font-medium tracking-tight">
                Lore keeps your agent’s role on this computer.
              </h2>
              <p className="max-w-prose text-sm leading-6 text-muted-foreground">
                Add the skills you want, shape them into a persona, and map a codebase if you have one.
                You can skip a step and finish it later. The dashboard opens when these steps are done.
              </p>
            </div>
          ) : null}
          {step === "skills" ? (
            <div className="flex flex-col gap-4">
              <div>
                <h2 id={titleId} className="text-xl font-medium">Which skills should Lore keep?</h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  Skills from skills.sh are the usual starting point. You can also add a markdown skill from this computer.
                  Nothing is required yet.
                </p>
              </div>
              <form className="flex gap-2" onSubmit={(event) => search(event).catch((exc: Error) => setError(exc.message))}>
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search skills.sh"
                  aria-label="Search skills.sh"
                />
                <Button type="submit">Search</Button>
                {results ? (
                  <Button type="button" variant="outline" onClick={() => setResults(null)}>
                    Suggested
                  </Button>
                ) : null}
              </form>
              <ul className="flex flex-col gap-2">
                {shown.map((skill) => {
                  const key = registryKey(skill)
                  const checked = picked.some((item) => registryKey(item) === key)
                  return (
                    <li key={key}>
                      <label className="flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2">
                        <input
                          type="checkbox"
                          className="mt-1 size-4 accent-foreground"
                          checked={checked}
                          onChange={() => toggleRegistry(skill)}
                        />
                        <span className="min-w-0">
                          <span className="block text-sm font-medium">{skill.name}</span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {skill.source} · {installs(skill.installs)}
                          </span>
                        </span>
                      </label>
                    </li>
                  )
                })}
                {shown.length === 0 ? <li className="text-sm text-muted-foreground">No skills to show yet.</li> : null}
              </ul>
              <Field>
                <FieldLabel htmlFor="skill-file">Add a skill from this computer</FieldLabel>
                <Input
                  id="skill-file"
                  type="file"
                  accept=".md,text/markdown,text/plain"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) addFile(file).catch((exc: Error) => setError(exc.message))
                    event.target.value = ""
                  }}
                />
                <FieldDescription>
                  {waiting.length === 0 ? "Markdown files wait here until a persona adopts them." : `${waiting.length} skill${waiting.length === 1 ? "" : "s"} waiting.`}
                </FieldDescription>
              </Field>
            </div>
          ) : null}
          {step === "persona" ? (
            <div className="flex flex-col gap-4">
              <div>
                <h2 id={titleId} className="text-xl font-medium">Create a persona for these skills</h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  A persona is the role your agent takes. Write it yourself, or save an API key and let that model draft it from the skills you check.
                </p>
              </div>
              <ul className="flex flex-col gap-2">
                {waiting.map((skill) => (
                  <li key={skill.id}>
                    <label className="flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2">
                      <input
                        type="checkbox"
                        className="mt-1 size-4 accent-foreground"
                        checked={chosenSkills.includes(skill.id)}
                        onChange={() =>
                          setChosenSkills((current) =>
                            current.includes(skill.id) ? current.filter((item) => item !== skill.id) : [...current, skill.id],
                          )
                        }
                      />
                      <span>
                        <span className="block text-sm font-medium">{skill.title}</span>
                        <span className="block text-xs text-muted-foreground">{skill.summary || "No summary yet."}</span>
                      </span>
                    </label>
                  </li>
                ))}
                {waiting.length === 0 ? (
                  <li className="text-sm text-muted-foreground">No skills are waiting. You can still write a persona, or skip and add skills later.</li>
                ) : null}
              </ul>
              <div className="flex gap-2">
                <Button type="button" variant={mode === "write" ? "default" : "outline"} onClick={() => setMode("write")}>
                  Write it yourself
                </Button>
                <Button type="button" variant={mode === "model" ? "default" : "outline"} onClick={() => setMode("model")}>
                  Draft with a model
                </Button>
              </div>
              {mode === "model" ? (
                <FieldGroup>
                  <Field>
                    <FieldLabel htmlFor="draft-provider">Provider</FieldLabel>
                    <Select
                      items={PROVIDERS}
                      value={provider}
                      onValueChange={(value) => {
                        if (!value) return
                        setProvider(value)
                        const defaults = defaultModels(value)
                        setModels(defaults)
                        setModel(defaults[0] ?? "")
                      }}
                    >
                      <SelectTrigger id="draft-provider" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {PROVIDERS.map((item) => (
                            <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="draft-key">API key</FieldLabel>
                    <Input id="draft-key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
                    <FieldDescription>The key stays in your persona library. Lore sends it only when you ask for a draft.</FieldDescription>
                  </Field>
                  <Button type="button" variant="outline" disabled={apiKey.trim().length < 8} onClick={() => saveKey().catch((exc: Error) => setError(exc.message))}>
                    Save key and load models
                  </Button>
                  <Field>
                    <FieldLabel htmlFor="draft-model">Model</FieldLabel>
                    <Select items={models.map((item) => ({ label: item, value: item }))} value={model} onValueChange={(value) => value && setModel(value)}>
                      <SelectTrigger id="draft-model" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {models.map((item) => (
                            <SelectItem key={item} value={item}>{item}</SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="draft-note">Note for the draft</FieldLabel>
                    <Textarea id="draft-note" rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
                  </Field>
                  <Button type="button" variant="outline" onClick={() => draft().catch((exc: Error) => setError(exc.message))}>
                    Draft persona
                  </Button>
                </FieldGroup>
              ) : null}
              <form className="flex flex-col gap-3" onSubmit={(event) => savePersona(event).catch((exc: Error) => setError(exc.message))}>
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
                  <Textarea id="persona-rules" rows={5} value={rules} onChange={(event) => setRules(event.target.value)} />
                </Field>
                <Button type="submit">Save persona</Button>
                {savedPersona ? <p className="text-sm text-muted-foreground">Persona saved as a draft. Approve it on the Personas page before an agent can use it.</p> : null}
              </form>
            </div>
          ) : null}
          {step === "codebase" ? (
            <div className="flex flex-col gap-4">
              <div>
                <h2 id={titleId} className="text-xl font-medium">Map a codebase</h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  Lore can build a short map of one project and include a slice of it when an agent asks for context. You can skip this and add a codebase later.
                </p>
              </div>
              <Field>
                <FieldLabel htmlFor="code-name">Name</FieldLabel>
                <Input id="code-name" value={codeName} onChange={(event) => setCodeName(event.target.value)} placeholder="This project" />
              </Field>
              <FolderPicker value={codePath} onChange={setCodePath} />
              {codePath ? <p className="font-mono text-xs text-muted-foreground">{codePath}</p> : null}
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 border-t px-6 py-4">
          {step === "welcome" ? (
            <Button type="button" disabled={busy} onClick={() => go("skills")}>
              Get started
            </Button>
          ) : null}
          {step === "skills" ? (
            <>
              <Button type="button" variant="outline" disabled={busy} onClick={() => go("persona")}>
                Skip for now
              </Button>
              <Button type="button" disabled={busy} onClick={() => continueSkills()}>
                {busy ? "Adding skills…" : "Continue"}
              </Button>
            </>
          ) : null}
          {step === "persona" ? (
            <>
              <Button type="button" variant="outline" disabled={busy} onClick={() => go("codebase")}>
                Skip for now
              </Button>
              <Button type="button" disabled={busy} onClick={() => go("codebase")}>
                Continue
              </Button>
            </>
          ) : null}
          {step === "codebase" ? (
            <>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setBusy(true)
                  persist("done", true)
                    .catch((exc: Error) => setError(exc.message))
                    .finally(() => setBusy(false))
                }}
              >
                Skip for now
              </Button>
              <Button type="button" disabled={busy || !codePath} onClick={() => mapCode()}>
                {busy ? "Mapping…" : "Map and open dashboard"}
              </Button>
            </>
          ) : null}
        </div>
      </div>
    </div>
  )
}

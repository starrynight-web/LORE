"use client"

import { useEffect, useId, useRef, useState } from "react"
import { CheckIcon, CopyIcon, RefreshCwIcon } from "lucide-react"
import { toast } from "sonner"

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
import { api, type Onboarding as OnboardingState, type RegistrySkill, type WaitingSkill } from "@/lib/api"
import { PROVIDERS } from "@/lib/providers"

const ORDER = ["welcome", "connect", "skills", "persona", "codebase"] as const
type Step = (typeof ORDER)[number]
type Panel = "wizard" | "connect" | "skills" | "persona" | "codebase"

const PREVIEW = [
  { n: "1", title: "Connect", text: "Wire Lore MCP into your coding editors." },
  { n: "2", title: "Skills", text: "Choose what the coding agent should know." },
  { n: "3", title: "Role & Project", text: "Attach skills to a role and map a folder." },
]

function installs(value: number) {
  if (value >= 1000) return `${Math.round(value / 1000)}k installs`
  return `${value} installs`
}

function registryKey(skill: RegistrySkill) {
  return `${skill.source}/${skill.skill_id}`
}

function startStep(panel: Panel, initial: string): Step {
  if (panel !== "wizard") return panel
  if (initial === "connect" || initial === "skills" || initial === "persona" || initial === "codebase" || initial === "welcome") return initial
  return "welcome"
}

export function Onboarding({
  initial,
  onDone,
  panel = "wizard",
  onClose,
}: {
  initial: OnboardingState
  onDone: () => void
  panel?: Panel
  onClose?: () => void
}) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState<Step>(startStep(panel, initial.step))
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [featured, setFeatured] = useState<RegistrySkill[]>([])
  const [results, setResults] = useState<RegistrySkill[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [query, setQuery] = useState("")
  const [picked, setPicked] = useState<RegistrySkill[]>([])
  const [waiting, setWaiting] = useState<WaitingSkill[]>([])
  const [chosenSkills, setChosenSkills] = useState<string[]>([])
  const [mode, setMode] = useState<"write" | "model">("write")
  const [provider, setProvider] = useState("groq")
  const [apiKey, setApiKey] = useState("")
  const [keyStatus, setKeyStatus] = useState<"idle" | "saving" | "saved">("idle")
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState("")
  const [name, setName] = useState("")
  const [summary, setSummary] = useState("")
  const [rules, setRules] = useState("")
  const [note, setNote] = useState("")
  const [codeName, setCodeName] = useState("")
  const [codePath, setCodePath] = useState("")
  const [savedPersona, setSavedPersona] = useState(false)
  const [waitingFilter, setWaitingFilter] = useState("")
  const [addProgress, setAddProgress] = useState<{ current: number; total: number; name: string } | null>(null)
  const [providerConfigured, setProviderConfigured] = useState(false)
  const [providerLast4, setProviderLast4] = useState("")
  const [connectCommand, setConnectCommand] = useState("uvx lore-solo connect")
  const [connectedEditors, setConnectedEditors] = useState<string[] | null>(null)
  const [projectMcpWritten, setProjectMcpWritten] = useState<string[] | null>(null)
  const [skillspectorInfo, setSkillspectorInfo] = useState<{ available: boolean; install: string } | null>(null)
  const [connectBusy, setConnectBusy] = useState(false)

  const index = Math.max(0, ORDER.indexOf(step))
  const shown = results ?? featured
  const dismissible = panel !== "wizard"
  const providerTitle = PROVIDERS.find((item) => item.value === provider)?.label ?? provider
  const filteredWaiting = waiting.filter((skill) => {
    const needle = waitingFilter.trim().toLowerCase()
    if (!needle) return true
    return (
      skill.title.toLowerCase().includes(needle) ||
      (skill.summary || "").toLowerCase().includes(needle)
    )
  })
  const allWaitingSelected = waiting.length > 0 && waiting.every((skill) => chosenSkills.includes(skill.id))

  useEffect(() => {
    const node = panelRef.current
    const focusable = node?.querySelector<HTMLElement>("button, input, textarea, select, [href]")
    focusable?.focus()
  }, [step])

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault()
        event.stopPropagation()
        if (dismissible) onClose?.()
        return
      }
      if (event.key !== "Tab" || !panelRef.current) return
      const items = [...panelRef.current.querySelectorAll<HTMLElement>("button, input, textarea, select, a[href], [tabindex='0']")].filter(
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
  }, [dismissible, onClose])

  function loadSkillspector() {
    api<{ available: boolean; install: string }>("/api/skillspector")
      .then(setSkillspectorInfo)
      .catch(() => {})
  }

  useEffect(() => {
    if (step !== "connect") return
    api<{ command: string }>("/api/connect")
      .then((row) => {
        if (row.command) setConnectCommand(row.command)
      })
      .catch(() => {})
    loadSkillspector()
  }, [step])

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
    api<{ provider: string; configured: boolean; last4: string; model: string }>("/api/provider")
      .then((row) => {
        if (!row.configured) {
          setProviderConfigured(false)
          setProviderLast4("")
          return
        }
        setProviderConfigured(true)
        setProviderLast4(row.last4)
        if (row.provider) setProvider(row.provider)
        if (row.model) {
          setModel(row.model)
          setModels([row.model])
        }
        setKeyStatus("saved")
        return api<{ model: string; models: string[] }>("/api/provider/models")
          .then((list) => {
            const catalog = list.models.length > 0 ? list.models : list.model ? [list.model] : []
            setModels(catalog)
            setModel(list.model || catalog[0] || row.model || "")
          })
          .catch(() => undefined)
      })
      .catch((exc: Error) => setError(exc.message))
  }, [step])

  async function persist(next: Step | "done", completed = false) {
    await api<OnboardingState>("/api/onboarding", {
      method: "POST",
      body: JSON.stringify({ step: completed ? "done" : next, completed }),
    })
    if (completed) onDone()
    else if (next !== "done") setStep(next)
  }

  async function go(next: Step) {
    setError("")
    setBusy(true)
    try {
      await persist(next)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "That step could not be saved.")
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
    setSearching(true)
    try {
      const row = await api<{ skills: RegistrySkill[] }>("/api/skills/search", {
        method: "POST",
        body: JSON.stringify({ query }),
      })
      setResults(row.skills)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The search did not finish.")
    } finally {
      setSearching(false)
    }
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

  async function addFiles(files: FileList | File[]) {
    const list = Array.from(files)
    for (const file of list) {
      await addFile(file)
    }
  }

  async function addFolderFromDisk() {
    setError("")
    setBusy(true)
    try {
      const pickedFolder = await api<{ path: string; name: string }>("/api/pick-folder", {
        method: "POST",
        body: JSON.stringify({ title: "Choose a skills folder" }),
      })
      if (!pickedFolder.path) return
      const row = await api<{ skills: WaitingSkill[]; count: number }>("/api/inbox/from-folder", {
        method: "POST",
        body: JSON.stringify({ path: pickedFolder.path }),
      })
      setWaiting((current) => {
        const next = [...current]
        for (const saved of row.skills) {
          const index = next.findIndex((item) => item.id === saved.id)
          if (index >= 0) next[index] = saved
          else next.push(saved)
        }
        return next
      })
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Those skill folders could not be added.")
    } finally {
      setBusy(false)
    }
  }

  async function addPicked() {
    const failed: string[] = []
    const total = picked.length
    for (let index = 0; index < picked.length; index += 1) {
      const skill = picked[index]
      setAddProgress({ current: index + 1, total, name: skill.name })
      try {
        const saved = await api<WaitingSkill>("/api/skills/add", {
          method: "POST",
          body: JSON.stringify({ source: skill.source, skill_id: skill.skill_id }),
        })
        setWaiting((current) => [...current.filter((item) => item.id !== saved.id), saved])
      } catch {
        failed.push(skill.name)
      }
    }
    setAddProgress(null)
    setPicked([])
    if (failed.length > 0) {
      throw new Error(`Could not add ${failed.join(", ")}. The others were added.`)
    }
  }

  async function continueSkills() {
    setError("")
    setBusy(true)
    setAddProgress(null)
    try {
      if (picked.length > 0) await addPicked()
      if (panel === "wizard") await persist("persona")
      else onDone()
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Those skills could not be added.")
    } finally {
      setBusy(false)
      setAddProgress(null)
    }
  }

  async function saveKey() {
    setError("")
    setKeyStatus("saving")
    try {
      const saved = await api<{ provider: string; configured: boolean; last4: string; model: string }>("/api/provider", {
        method: "POST",
        body: JSON.stringify({ provider, key: apiKey }),
      })
      setKeyStatus("saved")
      setApiKey("")
      setProviderConfigured(true)
      setProviderLast4(saved.last4)
      if (saved.provider) setProvider(saved.provider)
      if (saved.model) setModel(saved.model)
    } catch (exc) {
      setKeyStatus("idle")
      setError(exc instanceof Error ? exc.message : "The key could not be saved.")
      return
    }
    try {
      const list = await api<{ model: string; models: string[] }>("/api/provider/models")
      const catalog = list.models.length > 0 ? list.models : list.model ? [list.model] : []
      const current = model
      let chosen = (list.model && catalog.includes(list.model) ? list.model : "") || catalog[0] || ""
      if (current && current !== chosen && catalog.includes(current)) {
        await api("/api/provider/models", { method: "POST", body: JSON.stringify({ model: current }) })
        chosen = current
      }
      setModels(catalog)
      setModel(chosen)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The model list could not be loaded.")
    }
  }

  async function draft() {
    setError("")
    setBusy(true)
    try {
      // Only persist a model choice from this modal when the person just configured
      // a key here. Otherwise a default Groq model would overwrite Settings.
      if (!providerConfigured && model) {
        await api("/api/provider/models", { method: "POST", body: JSON.stringify({ model }) })
      }
      const drafted = await api<{ title: string; summary: string; rules: string }>("/api/provider/draft", {
        method: "POST",
        body: JSON.stringify({ note, skill_ids: chosenSkills }),
      })
      setName(drafted.title)
      setSummary(drafted.summary)
      setRules(drafted.rules)
      setMode("write")
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The draft could not be written.")
    } finally {
      setBusy(false)
    }
  }

  async function savePersona(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    setBusy(true)
    try {
      await api("/api/personas", {
        method: "POST",
        body: JSON.stringify({ name, summary, steps: rules, skill_ids: chosenSkills }),
      })
      if (panel === "wizard") {
        setSavedPersona(true)
        setName("")
        setSummary("")
        setRules("")
        setNote("")
      } else {
        onDone()
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The role could not be saved.")
    } finally {
      setBusy(false)
    }
  }

  async function mapCode() {
    setError("")
    setBusy(true)
    try {
      const created = await api<{ id: string }>("/api/codebases", {
        method: "POST",
        body: JSON.stringify({ name: codeName || "Codebase", path: codePath }),
      })
      if (panel === "wizard") {
        await api(`/api/codebases/${encodeURIComponent(created.id)}`, {
          method: "POST",
          body: JSON.stringify({ build: true }),
        })
        await persist("done", true)
      } else {
        onDone()
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "That folder could not be added.")
    } finally {
      setBusy(false)
    }
  }

  async function connectInstalledEditors() {
    setError("")
    setConnectBusy(true)
    try {
      const res = await api<{ written?: string[] }>("/api/connect/agents", { method: "POST" })
      setConnectedEditors(res.written ?? [])
      if (res.written && res.written.length > 0) {
        toast.success(`Connected ${res.written.length} editor config(s).`)
      } else {
        toast.info("No local editors detected automatically; use the command or project config below.")
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not connect editors.")
    } finally {
      setConnectBusy(false)
    }
  }

  async function writeProjectMcp() {
    setError("")
    setConnectBusy(true)
    try {
      const res = await api<{ written?: string[] }>("/api/connect", { method: "POST" })
      setProjectMcpWritten(res.written ?? [])
      toast.success("Project MCP configs written.")
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not write project MCP configs.")
    } finally {
      setConnectBusy(false)
    }
  }

  function copyValue(text: string, label: string) {
    navigator.clipboard.writeText(text).then(
      () => toast.success(label),
      () => toast.error("Could not copy to clipboard.")
    )
  }

  const previous = index > 0 ? ORDER[index - 1] : null
  const keyLabel = keyStatus === "saving" ? "Saving…" : keyStatus === "saved" ? "Key saved" : "Save key and load models"

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4 backdrop-blur-md dark:bg-black/60">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex max-h-[min(46rem,calc(100vh-2rem))] w-full max-w-2xl flex-col overflow-hidden rounded-[24px] border border-border bg-card text-card-foreground shadow-2xl"
      >
        <div className="flex items-center justify-between gap-3 border-b border-border px-6 py-4">
          {panel === "wizard" ? (
            <div className="flex flex-wrap items-center gap-1.5">
              {ORDER.map((item, idx) => {
                const active = item === step
                const done = idx < index
                const label =
                  item === "welcome"
                    ? "Welcome"
                    : item === "connect"
                      ? "1. Connect"
                      : item === "skills"
                        ? "2. Skills"
                        : item === "persona"
                          ? "3. Role"
                          : "4. Project"
                return (
                  <span
                    key={item}
                    className={
                      active
                        ? "rounded-full bg-primary px-3 py-1 text-[11px] font-semibold text-primary-foreground"
                        : done
                          ? "rounded-full bg-[#c8eb5e] px-3 py-1 text-[11px] font-semibold text-[#141517]"
                          : "rounded-full bg-muted px-3 py-1 text-[11px] font-medium text-muted-foreground"
                    }
                  >
                    {label}
                  </span>
                )
              })}
            </div>
          ) : (
            <span className="rounded-full bg-muted px-3 py-1 text-[11px] font-semibold tracking-wide text-foreground uppercase">
              {step === "skills" ? "Add skills" : step === "persona" ? "New persona" : "Add project"}
            </span>
          )}
          {dismissible ? (
            <Button type="button" variant="outline" size="sm" onClick={onClose}>
              Close
            </Button>
          ) : null}
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-5">
          {step !== "persona" ? <ErrorAlert message={error} /> : null}
          {step === "welcome" ? (
            <div className="flex flex-col gap-6 py-1">
              <div className="flex flex-col gap-2.5">
                <h2 id={titleId} className="text-[28px] font-bold tracking-[-0.03em] leading-[1.15] text-balance">
                  Keep your coding agent on one role.
                </h2>
                <p className="max-w-prose text-[13.5px] leading-6 text-muted-foreground">
                  Lore remembers the skills and the role on this computer. Your editor asks Lore what to follow.
                  You can skip any step and come back to it later.
                </p>
              </div>
              <ol className="grid gap-3 sm:grid-cols-3">
                {PREVIEW.map((item) => (
                  <li key={item.n} className="flex flex-col gap-2 rounded-2xl border border-border bg-muted/50 p-4">
                    <span className="grid size-6 place-items-center rounded-full bg-[#c8eb5e] text-[11px] font-bold text-[#141517]">
                      {item.n}
                    </span>
                    <span className="text-sm font-semibold">{item.title}</span>
                    <span className="text-xs leading-5 text-muted-foreground">{item.text}</span>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}
          {step === "connect" ? (
            <div className="flex flex-col gap-5">
              <div>
                <h2 id={titleId} className="text-xl font-bold tracking-[-0.02em]">
                  Connect your coding editors
                </h2>
                <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
                  Register Lore MCP with your editors so your coding agent can request skills and log receipts automatically.
                </p>
              </div>

              <div className="flex flex-col gap-3 rounded-2xl border border-border bg-muted/40 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold">Auto-connect installed editors</div>
                    <div className="text-xs text-muted-foreground">
                      Writes MCP &amp; standing rules for detected editors (Cursor, Claude, VS Code, Zed, etc.).
                    </div>
                  </div>
                  <Button type="button" size="sm" disabled={connectBusy} onClick={() => connectInstalledEditors()}>
                    {connectBusy ? "Connecting…" : "Connect editors"}
                  </Button>
                </div>
                {connectedEditors !== null ? (
                  <p className="text-xs text-muted-foreground">
                    {connectedEditors.length > 0
                      ? `Updated: ${connectedEditors.join(", ")}`
                      : "No editors auto-detected. Use the universal command or project config below."}
                  </p>
                ) : null}

                <div className="border-t border-border pt-3">
                  <div className="mb-1.5 text-xs font-semibold text-muted-foreground">
                    Or run / paste the universal command
                  </div>
                  <div className="flex items-center justify-between gap-2 rounded-2xl border border-border bg-card px-3.5 py-2">
                    <code className="truncate font-mono text-xs">{connectCommand}</code>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => copyValue(connectCommand, "Connect command copied.")}
                    >
                      <CopyIcon className="size-3" />
                      Copy
                    </Button>
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
                  <span className="text-xs text-muted-foreground">
                    {projectMcpWritten && projectMcpWritten.length > 0
                      ? `Written: ${projectMcpWritten.join(", ")}`
                      : "Fallback: write .mcp.json, .cursor/mcp.json, .vscode/mcp.json in this project"}
                  </span>
                  <Button type="button" size="sm" variant="outline" disabled={connectBusy} onClick={() => writeProjectMcp()}>
                    Write project configs
                  </Button>
                </div>
              </div>

              <div className="flex flex-col gap-3 rounded-2xl border border-border bg-muted/30 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold">SkillSpector security addon</span>
                      {skillspectorInfo?.available ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-[#c8eb5e] px-2.5 py-0.5 text-[11px] font-semibold text-[#141517]">
                          <CheckIcon className="size-3" />
                          Installed
                        </span>
                      ) : (
                        <span className="rounded-full bg-muted px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                          Optional
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      Lore already runs built-in ATR security rules before approving any skill. SkillSpector adds deeper external static checks if you want extra coverage — completely optional.
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => loadSkillspector()}
                    title="Re-check SkillSpector"
                    aria-label="Re-check SkillSpector"
                  >
                    <RefreshCwIcon className="size-3.5" />
                  </Button>
                </div>

                {!skillspectorInfo?.available ? (
                  <div className="flex items-center justify-between gap-2 rounded-2xl border border-border bg-card px-3.5 py-2">
                    <code className="truncate font-mono text-xs">
                      {skillspectorInfo?.install ?? "uv tool install git+https://github.com/NVIDIA/skillspector.git"}
                    </code>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() =>
                        copyValue(
                          skillspectorInfo?.install ?? "uv tool install git+https://github.com/NVIDIA/skillspector.git",
                          "SkillSpector install command copied."
                        )
                      }
                    >
                      <CopyIcon className="size-3" />
                      Copy
                    </Button>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
          {step === "skills" ? (
            <div className="flex flex-col gap-4">
              <div>
                <h2 id={titleId} className="text-xl font-bold tracking-[-0.02em]">Which skills should Lore keep?</h2>
                <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
                  Search skills.sh, or add markdown files and skill folders from this computer. Nothing is required yet.
                </p>
              </div>
              <form className="flex gap-2" onSubmit={(event) => search(event)}>
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search skills..."
                  aria-label="Search skills"
                  className="h-10 rounded-full bg-muted/60 px-4"
                />
                <Button type="submit" disabled={searching || query.trim().length < 2}>
                  {searching ? "Searching…" : "Search"}
                </Button>
                {results ? (
                  <Button type="button" variant="outline" onClick={() => setResults(null)} disabled={searching}>
                    Suggested
                  </Button>
                ) : null}
              </form>
              <ul
                className={
                  results
                    ? "flex h-[18rem] flex-col gap-2 overflow-y-auto pr-1"
                    : "flex max-h-[18rem] flex-col gap-2 overflow-y-auto pr-1"
                }
                aria-busy={searching}
                aria-live="polite"
              >
                {searching ? <li className="px-3 py-2 text-sm text-muted-foreground">Searching…</li> : null}
                {searching
                  ? null
                  : shown.map((skill) => {
                      const key = registryKey(skill)
                      const checked = picked.some((item) => registryKey(item) === key)
                      return (
                        <li key={key}>
                          <label
                            className={
                              checked
                                ? "flex cursor-pointer items-start gap-3 rounded-2xl border border-foreground/25 bg-[#c8eb5e]/20 px-3.5 py-2.5 transition-colors"
                                : "flex cursor-pointer items-start gap-3 rounded-2xl border border-border bg-muted/35 px-3.5 py-2.5 transition-colors hover:bg-muted/70"
                            }
                          >
                            <input
                              type="checkbox"
                              className="mt-1 size-4 accent-[#1c1d21] dark:accent-[#c8eb5e]"
                              checked={checked}
                              onChange={() => toggleRegistry(skill)}
                            />
                            <span className="min-w-0">
                              <span className="block text-sm font-semibold">{skill.name}</span>
                              <span className="block truncate text-xs text-muted-foreground">
                                {skill.source} · {installs(skill.installs)}
                              </span>
                            </span>
                          </label>
                        </li>
                      )
                    })}
                {!searching && results && shown.length === 0 ? (
                  <li className="text-sm text-muted-foreground">No skills matched that search.</li>
                ) : null}
                {!searching && !results && shown.length === 0 ? (
                  <li className="text-sm text-muted-foreground">No skills to show yet.</li>
                ) : null}
              </ul>
              <p className="text-sm text-muted-foreground" aria-live="polite">
                {picked.length === 0
                  ? "No skills.sh skills selected yet."
                  : `${picked.length} skill${picked.length === 1 ? "" : "s"} selected from skills.sh.`}
              </p>
              {addProgress ? (
                <p className="text-sm text-muted-foreground" aria-live="polite">
                  Downloading {addProgress.current} of {addProgress.total}: {addProgress.name}…
                </p>
              ) : null}
              <Field>
                <FieldLabel>Add from this computer</FieldLabel>
                <div className="flex flex-wrap gap-2">
                  <input
                    ref={fileInputRef}
                    id="skill-file"
                    type="file"
                    accept=".md,text/markdown,text/plain"
                    multiple
                    className="sr-only"
                    onChange={(event) => {
                      const files = event.target.files
                      if (files && files.length > 0) {
                        addFiles(files).catch((exc: Error) => setError(exc.message))
                      }
                      event.target.value = ""
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    Choose files
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() => addFolderFromDisk()}
                  >
                    {busy ? "Adding folders…" : "Choose folders"}
                  </Button>
                </div>
                <FieldDescription>
                  {waiting.length === 0
                    ? "Pick .md files, or a parent folder of skills.sh installs (each with SKILL.md). They wait here until you choose a role."
                    : `${waiting.length} skill${waiting.length === 1 ? "" : "s"} waiting for a role.`}
                </FieldDescription>
              </Field>
            </div>
          ) : null}
          {step === "persona" ? (
            <div className="flex flex-col gap-4">
              <div>
                <h2 id={titleId} className="text-xl font-medium">Create a role for these skills</h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  A role is the job you want the coding agent to do. Write it yourself, or let a model draft it from the skills you check. Save role writes the persona file.
                </p>
              </div>
              {waiting.length > 0 ? (
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Input
                      value={waitingFilter}
                      onChange={(event) => setWaitingFilter(event.target.value)}
                      placeholder="Search waiting skills"
                      aria-label="Search waiting skills"
                      className="min-w-[12rem] flex-1"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setChosenSkills(waiting.map((skill) => skill.id))}
                      disabled={allWaitingSelected}
                    >
                      Select all
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setChosenSkills([])}
                      disabled={chosenSkills.length === 0}
                    >
                      Deselect all
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground" aria-live="polite">
                    {chosenSkills.length} of {waiting.length} waiting skill{waiting.length === 1 ? "" : "s"} selected.
                  </p>
                </div>
              ) : null}
              <ul className="flex max-h-48 flex-col gap-2 overflow-y-auto">
                {filteredWaiting.map((skill) => (
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
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">{skill.title}</span>
                        <span className="block line-clamp-2 text-xs text-muted-foreground">
                          {skill.summary || "No summary yet."}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
                {waiting.length === 0 ? (
                  <li className="text-sm text-muted-foreground">No skills are waiting. You can still write a role, or skip and add skills later.</li>
                ) : null}
                {waiting.length > 0 && filteredWaiting.length === 0 ? (
                  <li className="text-sm text-muted-foreground">No waiting skills match that search.</li>
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
                  {providerConfigured ? (
                    <FieldDescription>
                      Using {providerTitle}
                      {model ? ` · ${model}` : ""}
                      {providerLast4 ? ` (key …${providerLast4})` : ""} from Settings. Change it there if you need a different provider.
                    </FieldDescription>
                  ) : (
                    <>
                      <Field>
                        <FieldLabel htmlFor="draft-provider">Provider</FieldLabel>
                        <Select
                          items={PROVIDERS}
                          value={provider}
                          onValueChange={(value) => {
                            if (!value) return
                            setProvider(value)
                            setModels([])
                            setModel("")
                            setKeyStatus("idle")
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
                        <Input
                          id="draft-key"
                          type="password"
                          autoComplete="off"
                          value={apiKey}
                          onChange={(event) => {
                            setApiKey(event.target.value)
                            if (keyStatus === "saved") setKeyStatus("idle")
                          }}
                        />
                        <FieldDescription>The key stays on this computer. Lore uses it only when you ask for a draft.</FieldDescription>
                      </Field>
                      <Button
                        type="button"
                        variant="outline"
                        disabled={keyStatus === "saving" || apiKey.trim().length < 8}
                        aria-live="polite"
                        onClick={() => saveKey()}
                      >
                        {keyLabel}
                      </Button>
                      <Field>
                        <FieldLabel htmlFor="draft-model">Model</FieldLabel>
                        <Select items={models.map((item) => ({ label: item, value: item }))} value={model} onValueChange={(value) => value && setModel(value)}>
                          <SelectTrigger id="draft-model" className="w-full" disabled={models.length === 0}>
                            <SelectValue placeholder="Save a key to load models" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectGroup>
                              {models.map((item) => (
                                <SelectItem key={item} value={item}>{item}</SelectItem>
                              ))}
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                        <FieldDescription>Only chat models returned by that provider for this key are listed.</FieldDescription>
                      </Field>
                    </>
                  )}
                  <Field>
                    <FieldLabel htmlFor="draft-note">Note for the draft</FieldLabel>
                    <Textarea id="draft-note" rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
                  </Field>
                  <ErrorAlert message={error} />
                  <Button type="button" variant="outline" disabled={busy || (!providerConfigured && keyStatus !== "saved")} onClick={() => draft()}>
                    {busy ? "Drafting…" : "Draft role"}
                  </Button>
                </FieldGroup>
              ) : null}
              <form className="flex flex-col gap-3" onSubmit={(event) => savePersona(event)}>
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
                  <Textarea
                    id="persona-rules"
                    rows={8}
                    value={rules}
                    onChange={(event) => setRules(event.target.value)}
                    className="min-h-40 text-sm leading-7 whitespace-pre-wrap"
                  />
                </Field>
                {mode === "write" ? <ErrorAlert message={error} /> : null}
                <Button type="submit" disabled={busy || !name.trim()}>{busy ? "Saving…" : "Save role"}</Button>
                {name.trim() && rules.trim() ? (
                  <p className="text-sm text-muted-foreground">Save role writes the persona file and attaches the checked skills.</p>
                ) : null}
                {savedPersona ? <p className="text-sm text-muted-foreground">Role saved as a draft. Approve it on the Personas page before an agent can use it.</p> : null}
              </form>
            </div>
          ) : null}
          {step === "codebase" ? (
            <div className="flex flex-col gap-4">
              <div>
                <h2 id={titleId} className="text-xl font-medium">Add a project</h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  Lore can make a short map of one project and use a piece of it when an agent asks for context. You can skip this and add a project later.
                </p>
              </div>
              <Field>
                <FieldLabel htmlFor="code-name">Name</FieldLabel>
                <Input id="code-name" value={codeName} onChange={(event) => setCodeName(event.target.value)} placeholder="This project" />
              </Field>
              <FolderPicker value={codePath} onChange={setCodePath} />
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t px-6 py-4">
          <div>
            {panel === "wizard" && previous && step !== "welcome" ? (
              <Button type="button" variant="ghost" disabled={busy} onClick={() => go(previous)}>
                Back
              </Button>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {step === "welcome" ? (
              <Button type="button" disabled={busy} onClick={() => go("connect")}>
                Get started
              </Button>
            ) : null}
            {step === "connect" ? (
              <>
                <Button type="button" variant="outline" disabled={busy} onClick={() => go("skills")}>
                  Skip for now
                </Button>
                <Button type="button" disabled={busy} onClick={() => go("skills")}>
                  Continue
                </Button>
              </>
            ) : null}
            {step === "skills" ? (
              <>
                {panel === "wizard" ? (
                  <Button type="button" variant="outline" disabled={busy} onClick={() => go("persona")}>
                    Skip for now
                  </Button>
                ) : null}
                <Button
                  type="button"
                  disabled={busy || (panel !== "wizard" && picked.length === 0 && waiting.length === 0)}
                  onClick={() => continueSkills()}
                >
                  {addProgress
                    ? `Downloading ${addProgress.current}/${addProgress.total}…`
                    : busy
                      ? "Adding skills…"
                      : panel === "wizard"
                        ? picked.length > 0
                          ? `Continue with ${picked.length}`
                          : "Continue"
                        : picked.length > 0
                          ? `Add selected (${picked.length})`
                          : "Add selected"}
                </Button>
              </>
            ) : null}
            {step === "persona" && panel === "wizard" ? (
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
                {panel === "wizard" ? (
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
                ) : null}
                <Button type="button" disabled={busy || !codePath} onClick={() => mapCode()}>
                  {busy ? "Adding…" : panel === "wizard" ? "Map and open dashboard" : "Add project"}
                </Button>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}

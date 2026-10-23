"use client"

import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"

type Store = { project: string; name: string; keeps_own: boolean }
type Provider = { provider: string; configured: boolean; last4: string; model: string }
type Waiting = { id: string; title: string; summary: string; source: string }
type Found = { name: string; skill_id: string; source: string; installs: number }
type Install = { command: string; prompt: string }

const PROVIDERS = [
  { label: "Groq", value: "groq" },
  { label: "OpenRouter", value: "openrouter" },
  { label: "Gemini", value: "gemini" },
  { label: "OpenAI", value: "openai" },
  { label: "Anthropic", value: "anthropic" },
]

export default function SetupPage() {
  const [store, setStore] = useState<Store | null>(null)
  const [provider, setProvider] = useState<Provider | null>(null)
  const [providerName, setProviderName] = useState("groq")
  const [key, setKey] = useState("")
  const [waiting, setWaiting] = useState<Waiting[]>([])
  const [query, setQuery] = useState("")
  const [found, setFound] = useState<Found[]>([])
  const [name, setName] = useState("")
  const [summary, setSummary] = useState("")
  const [rules, setRules] = useState("")
  const [install, setInstall] = useState<Install | null>(null)
  const [config, setConfig] = useState("")
  const [error, setError] = useState("")

  function reloadInbox() {
    return api<{ skills: Waiting[] }>("/api/inbox").then((row) => setWaiting(row.skills))
  }

  useEffect(() => {
    api<Store>("/api/workspace")
      .then(setStore)
      .catch((exc: Error) => setError(exc.message))
    api<Provider>("/api/provider")
      .then((row) => {
        setProvider(row)
        if (row.provider) setProviderName(row.provider)
      })
      .catch((exc: Error) => setError(exc.message))
    reloadInbox().catch((exc: Error) => setError(exc.message))
    api<Install>("/api/connect")
      .then(setInstall)
      .catch((exc: Error) => setError(exc.message))
  }, [])

  async function saveKey(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    const saved = await api<Provider>("/api/provider", {
      method: "POST",
      body: JSON.stringify({ provider: providerName, key }),
    })
    setProvider(saved)
    setKey("")
    toast.success("Key saved on this computer.")
  }

  async function searchSkills(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    const row = await api<{ skills: Found[] }>("/api/skills/search", {
      method: "POST",
      body: JSON.stringify({ query }),
    })
    setFound(row.skills)
  }

  async function addFound(skill: Found) {
    setError("")
    await api("/api/skills/add", {
      method: "POST",
      body: JSON.stringify({ source: skill.source, skill_id: skill.skill_id }),
    })
    await reloadInbox()
    toast.success(`${skill.name} is waiting for a persona.`)
  }

  async function addFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    setError("")
    for (const file of Array.from(files)) {
      const content = await file.text()
      await api("/api/inbox", {
        method: "POST",
        body: JSON.stringify({ name: file.name, content }),
      })
    }
    await reloadInbox()
    toast.success("Skill file added.")
  }

  async function removeWaiting(id: string) {
    setError("")
    await api(`/api/inbox/${encodeURIComponent(id)}`, { method: "DELETE" })
    await reloadInbox()
  }

  async function draftPersona() {
    setError("")
    const drafted = await api<{ title: string; summary: string; rules: string }>("/api/provider/draft", {
      method: "POST",
      body: JSON.stringify({ note: rules }),
    })
    setName(drafted.title)
    setSummary(drafted.summary)
    setRules(drafted.rules)
    toast.success("Draft ready. Read it, then save it.")
  }

  async function savePersona(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api("/api/personas", {
      method: "POST",
      body: JSON.stringify({ name, summary, rules, title: name, adopt: true }),
    })
    setName("")
    setSummary("")
    setRules("")
    await reloadInbox()
    toast.success("Persona saved as a draft. Approve it on Personas.")
  }

  async function copy(text: string, label: string) {
    await navigator.clipboard.writeText(text)
    toast.success(label)
  }

  async function writeConfig() {
    setError("")
    const data = await api<Record<string, unknown>>("/api/connect", { method: "POST" })
    setConfig(JSON.stringify(data, null, 2))
    toast.success("Project MCP config written.")
  }

  const project = store?.name || "This project"
  const providerLabel = PROVIDERS.find((item) => item.value === provider?.provider)?.label

  return (
    <Shell>
      <ErrorAlert message={error} />
      <div className="grid grid-cols-1 gap-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
        <Card>
          <CardHeader>
            <CardDescription>Project</CardDescription>
            <CardTitle className="text-2xl font-semibold">{project}</CardTitle>
          </CardHeader>
          <CardFooter className="text-sm text-muted-foreground">
            {store?.keeps_own ? "Keeps its own personas." : "Uses the shared persona library."}
          </CardFooter>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Provider</CardDescription>
            <CardTitle className="text-2xl font-semibold">{providerLabel || "None"}</CardTitle>
          </CardHeader>
          <CardFooter className="text-sm text-muted-foreground">
            {provider?.configured ? `Key ending in ${provider.last4}.` : "Save a key to draft a persona."}
          </CardFooter>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Waiting skills</CardDescription>
            <CardTitle className="text-2xl font-semibold tabular-nums">{waiting.length}</CardTitle>
          </CardHeader>
          <CardFooter className="text-sm text-muted-foreground">Attached when a persona is saved.</CardFooter>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Draft model</CardDescription>
            <CardTitle className="truncate text-2xl font-semibold">{provider?.model || "Default"}</CardTitle>
          </CardHeader>
          <CardFooter className="text-sm text-muted-foreground">Change the model on Settings.</CardFooter>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle><h2>Provider key</h2></CardTitle>
            <CardDescription>A Groq, OpenRouter, Gemini, OpenAI, or Anthropic key drafts the persona. The key stays on this computer.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={(event) => saveKey(event).catch((exc: Error) => setError(exc.message))}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="provider">Provider</FieldLabel>
                  <Select
                    items={PROVIDERS}
                    value={providerName}
                    onValueChange={(value) => {
                      if (value) setProviderName(value)
                    }}
                  >
                    <SelectTrigger id="provider" className="w-full">
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
                  <FieldLabel htmlFor="provider-key">API key</FieldLabel>
                  <Input
                    id="provider-key"
                    type="password"
                    autoComplete="off"
                    value={key}
                    onChange={(event) => setKey(event.target.value)}
                    required
                  />
                </Field>
                <Button type="submit">Save key</Button>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle><h2>Add skills</h2></CardTitle>
            <CardDescription>Search skills.sh, or choose skill files you already have. They wait here until the persona is saved.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <form onSubmit={(event) => searchSkills(event).catch((exc: Error) => setError(exc.message))}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="skill-query">Search skills.sh</FieldLabel>
                  <Input id="skill-query" value={query} onChange={(event) => setQuery(event.target.value)} />
                </Field>
                <Button type="submit">Search</Button>
              </FieldGroup>
            </form>
            {found.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Skill</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead className="text-right">Add</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {found.map((skill) => (
                    <TableRow key={`${skill.source}/${skill.skill_id}`}>
                      <TableCell>{skill.name}</TableCell>
                      <TableCell className="text-muted-foreground">{skill.source}</TableCell>
                      <TableCell className="text-right">
                        <Button type="button" size="sm" variant="outline" onClick={() => addFound(skill).catch((exc: Error) => setError(exc.message))}>
                          Add
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : null}
            <Field>
              <FieldLabel htmlFor="skill-file">Skill files</FieldLabel>
              <Input
                id="skill-file"
                type="file"
                accept=".md,text/markdown,text/plain"
                multiple
                onChange={(event) => {
                  addFiles(event.target.files).catch((exc: Error) => setError(exc.message))
                  event.target.value = ""
                }}
              />
            </Field>
            {waiting.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Waiting</TableHead>
                    <TableHead className="text-right">Remove</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {waiting.map((skill) => (
                    <TableRow key={skill.id}>
                      <TableCell>
                        <div className="font-medium">{skill.title}</div>
                        <div className="text-muted-foreground">{skill.summary || skill.source || "From a file"}</div>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button type="button" size="sm" variant="ghost" onClick={() => removeWaiting(skill.id).catch((exc: Error) => setError(exc.message))}>
                          Remove
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle><h2>Create a persona</h2></CardTitle>
            <CardDescription>The persona is a ruleset for the skills above. Write it, or draft it with the saved key and then edit it.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={(event) => savePersona(event).catch((exc: Error) => setError(exc.message))}>
              <FieldGroup>
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
                  <Textarea id="persona-rules" rows={6} value={rules} onChange={(event) => setRules(event.target.value)} />
                </Field>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!provider?.configured}
                    onClick={() => draftPersona().catch((exc: Error) => setError(exc.message))}
                  >
                    Draft with the saved key
                  </Button>
                  <Button type="submit" disabled={!store}>Save persona</Button>
                </div>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle><h2>Add Lore to an editor</h2></CardTitle>
            <CardDescription>Give this prompt to your agent, or copy the command and run it yourself. Restart the editor after that.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {install ? (
              <>
                <Field>
                  <FieldLabel htmlFor="install-prompt">Prompt</FieldLabel>
                  <Textarea id="install-prompt" readOnly rows={6} value={install.prompt} />
                  <Button type="button" variant="outline" onClick={() => copy(install.prompt, "Prompt copied.").catch((exc: Error) => setError(exc.message))}>
                    Copy prompt
                  </Button>
                </Field>
                <Field>
                  <FieldLabel htmlFor="install-command">Command</FieldLabel>
                  <Input id="install-command" readOnly value={install.command} className="font-mono" />
                  <Button type="button" variant="outline" onClick={() => copy(install.command, "Command copied.").catch((exc: Error) => setError(exc.message))}>
                    Copy command
                  </Button>
                </Field>
              </>
            ) : null}
            <FieldDescription>Or write .cursor/mcp.json in this project.</FieldDescription>
            <Button type="button" variant="outline" onClick={() => writeConfig().catch((exc: Error) => setError(exc.message))}>
              Write project MCP config
            </Button>
            {config ? <pre className="overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs whitespace-pre-wrap">{config}</pre> : null}
          </CardContent>
        </Card>
      </div>
    </Shell>
  )
}

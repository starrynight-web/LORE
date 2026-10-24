"use client"

import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
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
import { api } from "@/lib/api"
import { PROVIDERS, defaultModels } from "@/lib/providers"

const LABELS: Record<string, string> = Object.fromEntries(PROVIDERS.map((item) => [item.value, item.label]))

type Provider = { provider: string; configured: boolean; last4: string; model: string }
type ModelList = { provider: string; model: string; models: string[] }

export default function SettingsPage() {
  const [budget, setBudget] = useState("800")
  const [items, setItems] = useState("8")
  const [provider, setProvider] = useState<Provider | null>(null)
  const [providerName, setProviderName] = useState("groq")
  const [apiKey, setApiKey] = useState("")
  const [models, setModels] = useState<string[]>(defaultModels("groq"))
  const [model, setModel] = useState(defaultModels("groq")[0])
  const [savedCatalog, setSavedCatalog] = useState<string[]>([])
  const [listed, setListed] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    api<{ token_budget: number; max_items: number }>("/api/settings")
      .then((row) => {
        setBudget(String(row.token_budget))
        setItems(String(row.max_items))
      })
      .catch((exc: Error) => setError(exc.message))
    api<Provider>("/api/provider")
      .then((row) => {
        setProvider(row)
        if (row.provider) setProviderName(row.provider)
        if (row.model) {
          setModel(row.model)
          setModels([row.model])
        }
        if (!row.configured) return
        return api<ModelList>("/api/provider/models")
          .then((list) => {
            const catalog = list.models.length > 0 ? list.models : [list.model]
            setSavedCatalog(catalog)
            setModels(catalog)
            setModel(list.model)
            setListed(true)
          })
          .catch((exc: Error) => setError(exc.message))
      })
      .catch((exc: Error) => setError(exc.message))
  }, [])

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({ token_budget: Number(budget), max_items: Number(items) }),
    })
    toast.success("Settings saved.")
  }

  function showDefaults(name: string) {
    const defaults = defaultModels(name)
    setModels(defaults)
    setModel(defaults[0] ?? "")
    setListed(false)
  }

  async function saveKey(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    const picked = model
    const saved = await api<Provider>("/api/provider", {
      method: "POST",
      body: JSON.stringify({ provider: providerName, key: apiKey }),
    })
    setProvider(saved)
    setApiKey("")
    const list = await api<ModelList>("/api/provider/models")
    const catalog = list.models.length > 0 ? list.models : [list.model]
    let chosen = list.model
    if (picked && picked !== list.model && catalog.includes(picked)) {
      const updated = await api<Provider>("/api/provider/models", {
        method: "POST",
        body: JSON.stringify({ model: picked }),
      })
      chosen = updated.model
      setProvider(updated)
    }
    const shown = catalog.includes(chosen) ? catalog : [chosen, ...catalog]
    setSavedCatalog(shown)
    setModels(shown)
    setModel(chosen)
    setListed(true)
    toast.success("API key saved.")
  }

  async function clearKey() {
    setError("")
    const cleared = await api<Provider>("/api/provider", { method: "DELETE" })
    setProvider(cleared)
    setSavedCatalog([])
    showDefaults(providerName)
    toast.success("API key removed.")
  }

  async function saveModel() {
    setError("")
    const updated = await api<Provider>("/api/provider/models", {
      method: "POST",
      body: JSON.stringify({ model }),
    })
    setProvider(updated)
    setModel(updated.model)
    setSavedCatalog((current) => (current.includes(updated.model) ? current : [updated.model, ...current]))
    toast.success(`Drafts now use ${updated.model}.`)
  }

  const modelItems = models.map((item) => ({ label: item, value: item }))
  const providerLabel = LABELS[providerName] ?? providerName
  const savedLabel = provider?.provider ? LABELS[provider.provider] ?? provider.provider : ""

  return (
    <Shell>
      <ErrorAlert message={error} />
      <div className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle><h2>Answer size</h2></CardTitle>
            <CardDescription>
              These limits apply to every get_context answer. Lore counts tokens with the cl100k tokenizer, includes skill summaries before map nodes, and drops an item whole when it would pass either cap.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={(event) => save(event).catch((exc: Error) => setError(exc.message))}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="budget">Token budget</FieldLabel>
                  <Input id="budget" inputMode="numeric" value={budget} onChange={(event) => setBudget(event.target.value)} />
                  <FieldDescription>Maximum size of one answer. 800 is about a page. The persona summary is counted before any skill or map node.</FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="items">Maximum items</FieldLabel>
                  <Input id="items" inputMode="numeric" value={items} onChange={(event) => setItems(event.target.value)} />
                  <FieldDescription>Maximum number of skill summaries and codebase-map nodes returned together. The default is 8.</FieldDescription>
                </Field>
                <Button type="submit">Save settings</Button>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle><h2>Draft provider</h2></CardTitle>
            <CardDescription>
              {provider?.configured
                ? `${savedLabel} is saved. Lore shows only the last four characters of the key and sends it only when you draft a persona.`
                : "Save one provider key to draft personas. The key stays in the persona library on this computer and is never given to the coding agent."}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <form onSubmit={(event) => saveKey(event).catch((exc: Error) => setError(exc.message))}>
              <FieldGroup>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field>
                    <FieldLabel htmlFor="provider">Provider</FieldLabel>
                    <Select
                      items={PROVIDERS}
                      value={providerName}
                      onValueChange={(value) => {
                        if (!value) return
                        setProviderName(value)
                        if (provider?.configured && value === provider.provider && savedCatalog.length > 0) {
                          setModels(savedCatalog)
                          setModel(provider.model || savedCatalog[0])
                          setListed(true)
                          return
                        }
                        showDefaults(value)
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
                    <FieldDescription>Switching providers resets the draft model to that provider’s default until you pick another.</FieldDescription>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="model">Model</FieldLabel>
                    <Select
                      items={modelItems}
                      value={model}
                      onValueChange={(value) => {
                        if (value) setModel(value)
                      }}
                    >
                      <SelectTrigger id="model" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {modelItems.map((item) => (
                            <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                    <FieldDescription>
                      {provider?.configured && listed && providerName === provider.provider
                        ? `These are the models the saved ${providerLabel} key can call. Later persona drafts use the one you save.`
                        : `Shown first is ${providerLabel || "Groq"}’s default. Save a key to replace this with the models that key can call.`}
                    </FieldDescription>
                  </Field>
                </div>
                <Field>
                  <FieldLabel htmlFor="api-key">API key</FieldLabel>
                  <Input id="api-key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={provider?.configured ? `Saved key ending ${provider.last4}` : "Paste a key"} />
                  <FieldDescription>Used only to list models and draft a persona. Replacing the key for the same provider keeps the model you already chose.</FieldDescription>
                </Field>
                <div className="flex flex-wrap gap-2">
                  <Button type="submit" disabled={apiKey.trim().length < 8}>Save API key</Button>
                  <Button type="button" variant="outline" disabled={!provider?.configured || !model || providerName !== provider.provider} onClick={() => saveModel().catch((exc: Error) => setError(exc.message))}>
                    Save model
                  </Button>
                  {provider?.configured ? (
                    <Button type="button" variant="outline" onClick={() => clearKey().catch((exc: Error) => setError(exc.message))}>
                      Remove key
                    </Button>
                  ) : null}
                </div>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>
      </div>
    </Shell>
  )
}

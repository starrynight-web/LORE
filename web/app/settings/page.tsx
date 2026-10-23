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

const LABELS: Record<string, string> = {
  groq: "Groq",
  openrouter: "OpenRouter",
  gemini: "Gemini",
  openai: "OpenAI",
  anthropic: "Anthropic",
}

type Provider = { provider: string; configured: boolean; last4: string; model: string }
type ModelList = { provider: string; model: string; models: string[] }

export default function SettingsPage() {
  const [budget, setBudget] = useState("800")
  const [items, setItems] = useState("8")
  const [provider, setProvider] = useState<Provider | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState("")
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
        if (row.model) {
          setModel(row.model)
          setModels([row.model])
        }
        if (!row.configured) return
        return api<ModelList>("/api/provider/models")
          .then((list) => {
            setModels(list.models.length > 0 ? list.models : [list.model])
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

  async function saveModel(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    const updated = await api<Provider>("/api/provider/models", {
      method: "POST",
      body: JSON.stringify({ model }),
    })
    setProvider(updated)
    setModel(updated.model)
    toast.success(`Drafts now use ${updated.model}.`)
  }

  const modelItems = models.map((item) => ({ label: item, value: item }))
  const providerLabel = provider?.provider ? LABELS[provider.provider] ?? provider.provider : ""

  return (
    <Shell>
      <ErrorAlert message={error} />
      <div className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle><h2>Answer size</h2></CardTitle>
            <CardDescription>How much of a persona comes back in one answer.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={(event) => save(event).catch((exc: Error) => setError(exc.message))}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="budget">Token budget</FieldLabel>
                  <Input id="budget" inputMode="numeric" value={budget} onChange={(event) => setBudget(event.target.value)} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="items">Maximum items</FieldLabel>
                  <Input id="items" inputMode="numeric" value={items} onChange={(event) => setItems(event.target.value)} />
                </Field>
                <Button type="submit">Save settings</Button>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle><h2>Draft model</h2></CardTitle>
            <CardDescription>
              {provider?.configured && listed
                ? `These are the models the saved ${providerLabel} key can call.`
                : provider?.configured
                  ? "The saved model stays selected until the provider returns its list."
                  : "Save a provider key on Setup. The model list appears here after that."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={(event) => saveModel(event).catch((exc: Error) => setError(exc.message))}>
              <FieldGroup>
                <Field data-disabled={!provider?.configured || models.length === 0 ? true : undefined}>
                  <FieldLabel htmlFor="model">Model</FieldLabel>
                  <Select
                    items={modelItems}
                    value={model}
                    disabled={!provider?.configured || models.length === 0}
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
                  <FieldDescription>Persona drafts use the model you save here.</FieldDescription>
                </Field>
                <Button type="submit" disabled={!provider?.configured || !model}>Save model</Button>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>
      </div>
    </Shell>
  )
}

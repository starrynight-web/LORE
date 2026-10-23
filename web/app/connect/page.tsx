"use client"

import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

type Install = { command: string; prompt: string }

export default function ConnectPage() {
  const [install, setInstall] = useState<Install | null>(null)
  const [config, setConfig] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    api<Install>("/api/connect")
      .then(setInstall)
      .catch((exc: Error) => setError(exc.message))
  }, [])

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

  return (
    <Shell>
      <ErrorAlert message={error} />
      <div className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle><h2>Prompt for your agent</h2></CardTitle>
            <CardDescription>It registers Lore with the editors already installed. Restart the editor after that.</CardDescription>
          </CardHeader>
          <CardContent>
            {install ? (
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="agent-prompt">Prompt</FieldLabel>
                  <Textarea id="agent-prompt" readOnly rows={8} value={install.prompt} />
                  <Button type="button" variant="outline" onClick={() => copy(install.prompt, "Prompt copied.").catch((exc: Error) => setError(exc.message))}>
                    Copy prompt
                  </Button>
                </Field>
                <Field>
                  <FieldLabel htmlFor="agent-command">Command</FieldLabel>
                  <Input id="agent-command" readOnly value={install.command} className="font-mono" />
                  <Button type="button" variant="outline" onClick={() => copy(install.command, "Command copied.").catch((exc: Error) => setError(exc.message))}>
                    Copy command
                  </Button>
                </Field>
              </FieldGroup>
            ) : (
              <p className="text-sm text-muted-foreground">Loading the install command…</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle><h2>One project only</h2></CardTitle>
            <CardDescription>Write .cursor/mcp.json in this project. Use this when an agent cannot run the command.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <FieldDescription>This config is a backup for the open project.</FieldDescription>
            <Button type="button" variant="outline" onClick={() => writeConfig().catch((exc: Error) => setError(exc.message))}>
              Write project MCP config
            </Button>
            {config ? (
              <>
                <pre className="overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs whitespace-pre-wrap">{config}</pre>
                <Button type="button" onClick={() => copy(config, "Config copied.").catch((exc: Error) => setError(exc.message))}>
                  Copy
                </Button>
              </>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </Shell>
  )
}

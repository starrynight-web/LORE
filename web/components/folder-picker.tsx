"use client"

import { useState } from "react"

import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"

function folderName(path: string) {
  const parts = path.split(/[/\\]/).filter(Boolean)
  return parts[parts.length - 1] ?? ""
}

export function FolderPicker({
  value,
  onChange,
}: {
  value: string
  onChange: (path: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const name = folderName(value)

  async function choose() {
    setBusy(true)
    setError("")
    try {
      const row = await api<{ path: string; name: string }>("/api/pick-folder", { method: "POST" })
      if (row.path) onChange(row.path)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The folder window could not open.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <Button type="button" variant="outline" onClick={() => choose()} disabled={busy}>
        {busy ? "Waiting for a folder…" : name ? "Change folder" : "Choose a folder"}
      </Button>
      <p className="text-sm text-muted-foreground">
        {name ? `Selected folder: ${name}` : "No folder selected yet."}
      </p>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
    </div>
  )
}

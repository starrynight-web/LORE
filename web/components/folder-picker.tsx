"use client"

import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"

type Child = { name: string; path: string }
type Listing = { path: string; parent: string; children: Child[] }

export function FolderPicker({
  value,
  onChange,
}: {
  value: string
  onChange: (path: string) => void
}) {
  const [listing, setListing] = useState<Listing | null>(null)
  const [error, setError] = useState("")

  function open(path?: string) {
    const query = path ? `?path=${encodeURIComponent(path)}` : ""
    api<Listing>(`/api/browse${query}`)
      .then((row) => {
        setListing(row)
        setError("")
      })
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    open(value || undefined)
    // The first folder shown is the open project. Later moves are explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="flex flex-col gap-2">
      <p className="truncate font-mono text-xs text-muted-foreground">{listing?.path ?? "Choose a folder"}</p>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <div className="flex flex-wrap gap-2">
        {listing?.parent ? (
          <Button type="button" variant="outline" size="sm" onClick={() => open(listing.parent)}>
            Up
          </Button>
        ) : null}
        <Button type="button" size="sm" onClick={() => listing && onChange(listing.path)} disabled={!listing}>
          Use this folder
        </Button>
      </div>
      <ul className="max-h-40 overflow-y-auto rounded-lg border">
        {(listing?.children ?? []).map((child) => (
          <li key={child.path}>
            <button
              type="button"
              className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
              onClick={() => open(child.path)}
            >
              {child.name}
            </button>
          </li>
        ))}
        {listing && listing.children.length === 0 ? (
          <li className="px-3 py-2 text-sm text-muted-foreground">No folders inside this one.</li>
        ) : null}
      </ul>
    </div>
  )
}

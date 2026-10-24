"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Onboarding } from "@/components/onboarding"
import { Shell } from "@/components/Shell"
import { api, type Codebase } from "@/lib/api"
import { codebaseHref } from "@/lib/routes"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"

function folderName(path: string) {
  const parts = path.split(/[/\\]/).filter(Boolean)
  return parts[parts.length - 1] ?? "Folder"
}

export default function CodebasePage() {
  const [rows, setRows] = useState<Codebase[]>([])
  const [error, setError] = useState("")
  const [open, setOpen] = useState(false)

  function reload() {
    api<{ codebases: Codebase[] }>("/api/codebases")
      .then((row) => setRows(row.codebases))
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
  }, [])

  async function remove(id: string) {
    setError("")
    await api(`/api/codebases/${encodeURIComponent(id)}`, { method: "DELETE" })
    toast.success("Codebase and its map files were removed.")
    reload()
  }

  return (
    <Shell>
      <ErrorAlert message={error} />
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-medium">Projects</h2>
          <p className="text-sm text-muted-foreground">Choose a folder. Lore can build a map inside it. Your files stay where they are.</p>
        </div>
        <Button type="button" size="sm" onClick={() => setOpen(true)}>
          Add project
        </Button>
      </div>
      <section className="flex flex-col gap-3">
        {rows.length === 0 ? <p className="text-sm text-muted-foreground">No project yet. Add a folder, then open it to build the map.</p> : null}
        <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
          {rows.map((row) => (
            <Card key={row.id}>
              <CardHeader>
                <Badge variant={row.map.state === "ready" ? "secondary" : "outline"}>{row.map.state}</Badge>
                <CardTitle>
                  <Link href={codebaseHref(row.id)} className="hover:underline">{row.name}</Link>
                </CardTitle>
                <CardDescription>{folderName(row.path)}</CardDescription>
              </CardHeader>
              <CardFooter className="gap-2">
                <Button variant="outline" nativeButton={false} render={<Link href={codebaseHref(row.id)} />}>Open</Button>
                <Button type="button" variant="destructive" onClick={() => remove(row.id).catch((exc: Error) => setError(exc.message))}>
                  Delete
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </section>
      {open ? (
        <Onboarding
          panel="codebase"
          initial={{ completed: true, step: "done" }}
          onDone={() => {
            setOpen(false)
            toast.success("Project added.")
            reload()
          }}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </Shell>
  )
}

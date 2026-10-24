"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { FolderPicker } from "@/components/folder-picker"
import { Shell } from "@/components/Shell"
import { api, type Codebase } from "@/lib/api"
import { codebaseHref } from "@/lib/routes"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"

export default function CodebasePage() {
  const [rows, setRows] = useState<Codebase[]>([])
  const [name, setName] = useState("")
  const [path, setPath] = useState("")
  const [error, setError] = useState("")

  function reload() {
    api<{ codebases: Codebase[] }>("/api/codebases")
      .then((row) => setRows(row.codebases))
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
  }, [])

  async function create(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api("/api/codebases", { method: "POST", body: JSON.stringify({ name, path }) })
    setName("")
    toast.success("Codebase added.")
    reload()
  }

  async function remove(id: string) {
    setError("")
    await api(`/api/codebases/${encodeURIComponent(id)}`, { method: "DELETE" })
    toast.success("Codebase and its map files were removed.")
    reload()
  }

  return (
    <Shell>
      <ErrorAlert message={error} />
      <Card>
        <CardHeader>
          <CardTitle><h2>Add a codebase</h2></CardTitle>
          <CardDescription>
            Pick a project folder. Mapping writes graphify-out and a status file inside that folder. Your source files stay.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-4" onSubmit={(event) => create(event).catch((exc: Error) => setError(exc.message))}>
            <Field>
              <FieldLabel htmlFor="code-name">Name</FieldLabel>
              <Input id="code-name" value={name} onChange={(event) => setName(event.target.value)} required />
            </Field>
            <FolderPicker value={path} onChange={setPath} />
            {path ? <p className="font-mono text-xs text-muted-foreground">{path}</p> : null}
            <Button type="submit" disabled={!path}>Add codebase</Button>
          </form>
        </CardContent>
      </Card>
      <section className="flex flex-col gap-3">
        <h2 className="text-base font-medium">Mapped codebases</h2>
        {rows.length === 0 ? <p className="text-sm text-muted-foreground">No codebase yet. Add a folder, then open it to build the map.</p> : null}
        <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2">
          {rows.map((row) => (
            <Card key={row.id}>
              <CardHeader>
                <Badge variant={row.map.state === "ready" ? "secondary" : "outline"}>{row.map.state}</Badge>
                <CardTitle>
                  <Link href={codebaseHref(row.id)} className="hover:underline">{row.name}</Link>
                </CardTitle>
                <CardDescription className="truncate font-mono text-xs">{row.path}</CardDescription>
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
    </Shell>
  )
}

"use client"

import { useParams, useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api, type Codebase } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export default function CodebaseDetailPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const id = decodeURIComponent(params.id)
  const [row, setRow] = useState<Codebase | null>(null)
  const [name, setName] = useState("")
  const [error, setError] = useState("")

  function reload() {
    api<Codebase>(`/api/codebases/${encodeURIComponent(id)}`)
      .then((loaded) => {
        setRow(loaded)
        setName(loaded.name)
      })
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
  }, [id])

  useEffect(() => {
    if (row?.map.state !== "running") return
    const timer = window.setInterval(reload, 1000)
    return () => window.clearInterval(timer)
  }, [row?.map.state])

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setError("")
    await api(`/api/codebases/${encodeURIComponent(id)}`, {
      method: "POST",
      body: JSON.stringify({ name }),
    })
    toast.success("Name updated.")
    reload()
  }

  async function build() {
    setError("")
    await api(`/api/codebases/${encodeURIComponent(id)}`, {
      method: "POST",
      body: JSON.stringify({ build: true }),
    })
    reload()
  }

  async function remove() {
    setError("")
    await api(`/api/codebases/${encodeURIComponent(id)}`, { method: "DELETE" })
    toast.success("Codebase removed.")
    router.push("/codebase")
  }

  const links = row?.map.links ?? []
  const ready = row?.map.state === "ready"

  return (
    <Shell>
      <ErrorAlert message={error} />
      {row ? (
        <>
          <Card>
            <CardHeader>
              <Badge variant={ready ? "secondary" : "outline"}>{row.map.state}</Badge>
              <CardTitle className="text-2xl">{row.name}</CardTitle>
              <CardDescription>{row.name}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <form className="flex flex-col gap-3" onSubmit={(event) => save(event).catch((exc: Error) => setError(exc.message))}>
                <Field>
                  <FieldLabel htmlFor="name">Name</FieldLabel>
                  <Input id="name" value={name} onChange={(event) => setName(event.target.value)} required />
                </Field>
                <div className="flex flex-wrap gap-2">
                  <Button type="submit">Save name</Button>
                  <Button type="button" variant="outline" disabled={row.map.state === "running"} onClick={() => build().catch((exc: Error) => setError(exc.message))}>
                    {ready ? "Update map" : "Map codebase"}
                  </Button>
                  <Button type="button" variant="destructive" onClick={() => remove().catch((exc: Error) => setError(exc.message))}>
                    Delete codebase
                  </Button>
                </div>
              </form>
              {row.map.error ? <p className="text-sm text-destructive">{row.map.error}</p> : null}
            </CardContent>
          </Card>
          {links.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle><h2>Links</h2></CardTitle>
                <CardDescription>Extracted links were read from the code. Inferred links were guessed.</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>From</TableHead>
                      <TableHead>Relation</TableHead>
                      <TableHead>To</TableHead>
                      <TableHead>Confidence</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {links.map((link) => (
                      <TableRow key={`${link.node}-${link.relation}-${link.to}`}>
                        <TableCell className="font-mono text-xs">{link.node}</TableCell>
                        <TableCell>{link.relation}</TableCell>
                        <TableCell className="font-mono text-xs">{link.to}</TableCell>
                        <TableCell>{link.confidence}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : null}
          {ready ? (
            <Card>
              <CardHeader>
                <CardTitle><h2>Map</h2></CardTitle>
              </CardHeader>
              <CardContent>
                <iframe
                  title="Codebase map"
                  src={`/api/codebases/${encodeURIComponent(id)}/graph`}
                  className="h-[480px] w-full rounded-lg border bg-background"
                />
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Loading codebase…</p>
      )}
    </Shell>
  )
}

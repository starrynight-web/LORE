"use client"

import { useEffect, useState } from "react"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

type GraphLink = { node: string; to: string; relation: string; confidence: string }
type GraphStatus = { state: string; time?: string; error?: string; schema_version?: number; links: GraphLink[] }

export default function CodebasePage() {
  const [status, setStatus] = useState<GraphStatus | null>(null)
  const [error, setError] = useState("")

  function reload() {
    api<GraphStatus>("/api/graph")
      .then(setStatus)
      .catch((exc: Error) => setError(exc.message))
  }

  useEffect(() => {
    reload()
  }, [])

  useEffect(() => {
    if (status?.state !== "running") return
    const timer = window.setInterval(reload, 1000)
    return () => window.clearInterval(timer)
  }, [status?.state])

  async function build() {
    setError("")
    await api("/api/graph/build", { method: "POST" })
    reload()
  }

  const ready = status?.state === "ready"
  const lede =
    status?.state === "running"
      ? "Mapping the codebase…"
      : status?.state === "failed"
        ? status.error
        : status?.state === "ready"
          ? `Map ready ${status.time ?? ""}`.trim()
          : "This project has not been mapped."

  return (
    <Shell>
      <ErrorAlert message={error} />
      <Card>
        <CardHeader>
          <CardDescription>Codebase map</CardDescription>
          <CardTitle className="text-2xl">{lede}</CardTitle>
        </CardHeader>
        <CardContent>
          <Button type="button" onClick={() => build().catch((exc: Error) => setError(exc.message))} disabled={status?.state === "running"}>
            {ready ? "Update map" : "Map codebase"}
          </Button>
        </CardContent>
      </Card>
      {(status?.links ?? []).length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle><h2>Links</h2></CardTitle>
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
                {(status?.links ?? []).map((link) => (
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
            <iframe title="Codebase map" src="/graph/view/" className="h-[480px] w-full rounded-lg border bg-background" />
          </CardContent>
        </Card>
      ) : null}
    </Shell>
  )
}

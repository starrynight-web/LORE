"use client"

import { useEffect, useState } from "react"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

type Decision = {
  id: string
  time: string
  persona: string
  verdict: string
  included: string[]
  summary: string
}

export default function ReplayPage() {
  const [rows, setRows] = useState<Decision[]>([])
  const [error, setError] = useState("")

  useEffect(() => {
    api<{ decisions: Decision[] }>("/api/decisions")
      .then((data) => setRows(data.decisions))
      .catch((exc: Error) => setError(exc.message))
  }, [])

  return (
    <Shell>
      <ErrorAlert message={error} />
      {rows.length === 0 ? <p className="text-sm text-muted-foreground">No decisions yet.</p> : null}
      <div className="flex flex-col gap-4">
        {rows.map((row) => (
          <Card key={row.id}>
            <CardHeader>
              <CardDescription>{row.id} · {row.time}</CardDescription>
              <CardTitle>
                <h2>{row.persona || row.verdict}</h2>
              </CardTitle>
              <Badge variant="outline">{row.verdict}</Badge>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <p>{row.summary}</p>
              {row.included.length ? (
                <p className="font-mono text-xs whitespace-pre-wrap text-muted-foreground">{row.included.join("\n")}</p>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>
    </Shell>
  )
}

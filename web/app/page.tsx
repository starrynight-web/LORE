"use client"

import { useEffect, useState } from "react"
import Link from "next/link"

import { ErrorAlert } from "@/components/error-alert"
import { Shell } from "@/components/Shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, type Rank, type Usage } from "@/lib/api"
import { personaHref, skillHref } from "@/lib/routes"

function RankTable({ rows, empty, href }: { rows: Rank[]; empty: string; href?: (id: string) => string }) {
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead className="text-right">Calls</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id}>
            <TableCell>
              {href ? (
                <Link href={href(row.id)} className="hover:underline">
                  {row.name}
                </Link>
              ) : (
                row.name
              )}
            </TableCell>
            <TableCell className="text-right tabular-nums">{row.count}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export default function DashboardPage() {
  const [usage, setUsage] = useState<Usage | null>(null)
  const [prompt, setPrompt] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    api<Usage>("/api/stats")
      .then(setUsage)
      .catch((exc: Error) => setError(exc.message))
    api<{ prompt: string }>("/api/connect")
      .then((row) => setPrompt(row.prompt))
      .catch((exc: Error) => setError(exc.message))
  }, [])

  const topAgent = usage?.agents[0]
  const topPersona = usage?.personas[0]
  const topSkill = usage?.skills[0]

  return (
    <Shell>
      <ErrorAlert message={error} />
      <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
        <Card>
          <CardHeader>
            <CardDescription>Calls</CardDescription>
            <CardTitle className="text-3xl tabular-nums">{usage?.calls ?? "—"}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">Times an agent asked Lore for context.</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Most active agent</CardDescription>
            <CardTitle className="text-2xl">{topAgent?.name ?? "None yet"}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">{topAgent ? `${topAgent.count} calls` : "Connect an editor to start."}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Most used persona</CardDescription>
            <CardTitle className="text-2xl">{topPersona?.name ?? "None yet"}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">{topPersona ? `${topPersona.count} calls` : "Approve a persona first."}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Most used skill</CardDescription>
            <CardTitle className="text-2xl">{topSkill?.name ?? "None yet"}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">{topSkill ? `${topSkill.count} calls` : "Skills appear after a call cites them."}</CardContent>
        </Card>
      </div>
      <div className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle><h2>Agents</h2></CardTitle>
            <CardDescription>Which editor started the Lore process.</CardDescription>
          </CardHeader>
          <CardContent>
            <RankTable rows={usage?.agents ?? []} empty="No agent has called Lore yet." />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle><h2>Personas</h2></CardTitle>
            <CardDescription>Roles agents asked for.</CardDescription>
          </CardHeader>
          <CardContent>
            <RankTable rows={usage?.personas ?? []} empty="No persona has been requested." href={personaHref} />
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle><h2>Skills</h2></CardTitle>
          <CardDescription>Skill summaries that fitted into an answer.</CardDescription>
        </CardHeader>
        <CardContent>
          <RankTable rows={usage?.skills ?? []} empty="No skill has been cited yet." href={skillHref} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle><h2>Recent calls</h2></CardTitle>
        </CardHeader>
        <CardContent>
          {(usage?.recent ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">Calls show up here after an agent uses Lore.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Persona</TableHead>
                  <TableHead>Verdict</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {usage?.recent.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-mono text-xs">{row.time}</TableCell>
                    <TableCell>{row.client}</TableCell>
                    <TableCell>{row.persona}</TableCell>
                    <TableCell><Badge variant="outline">{row.verdict}</Badge></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      {prompt ? (
        <Card>
          <CardHeader>
            <CardTitle><h2>Connect an editor</h2></CardTitle>
            <CardDescription>Paste this prompt into an agent, or run the connect command yourself. Each editor Lore registers is counted separately.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <pre className="overflow-x-auto rounded-lg border bg-muted p-3 text-xs whitespace-pre-wrap">{prompt}</pre>
            <Button
              type="button"
              variant="outline"
              onClick={() => navigator.clipboard.writeText(prompt)}
            >
              Copy prompt
            </Button>
          </CardContent>
        </Card>
      ) : null}
    </Shell>
  )
}

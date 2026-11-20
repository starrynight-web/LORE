"use client"

import Link from "next/link"

import type { Rank } from "@/lib/api"
import { skillHref } from "@/lib/routes"

const BAR_COLORS = ["#8fbc8f", "#a59bf3", "#c5c8d0", "#8fbc8f", "#a59bf3"]

export function SkillBarChart({ rows }: { rows: Rank[] }) {
  const top = rows.slice(0, 5)

  if (top.length === 0) {
    return (
      <div className="flex h-[185px] items-center justify-center rounded-2xl bg-muted/60 px-4 text-center text-xs text-muted-foreground">
        Skill call counts appear here once an agent cites skills via{" "}
        <code className="mx-1 font-mono">get_context</code>.
      </div>
    )
  }

  const maxCount = Math.max(...top.map((r) => r.count), 1)

  return (
    <div className="flex flex-col gap-3 pt-1">
      {top.map((row, idx) => {
        const pct = Math.max(12, Math.round((row.count / maxCount) * 100))
        const color = BAR_COLORS[idx % BAR_COLORS.length]
        return (
          <Link
            key={row.id}
            href={skillHref(row.id)}
            className="group flex flex-col gap-1"
          >
            <div className="flex items-center justify-between text-xs">
              <span className="truncate font-medium text-foreground group-hover:underline">
                {row.name}
              </span>
              <span className="font-mono text-[11px] font-semibold text-muted-foreground tabular-nums">
                {row.count} {row.count === 1 ? "call" : "calls"}
              </span>
            </div>
            <div className="h-6 w-full overflow-hidden rounded-full bg-muted p-0.5">
              <div
                className="flex h-full items-center rounded-full transition-all duration-300"
                style={{ width: `${pct}%`, background: color }}
              />
            </div>
          </Link>
        )
      })}
    </div>
  )
}

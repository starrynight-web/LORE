"use client"

import { useId, useState } from "react"

import type { TokenPoint } from "@/lib/api"

export function TokenSplineChart({
  series,
  budget,
}: {
  series: TokenPoint[]
  budget: number
}) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const gradId = useId()

  if (series.length === 0) {
    return (
      <div className="flex h-[130px] items-center justify-center rounded-2xl bg-muted/60 px-4 text-center text-xs text-muted-foreground">
        Token telemetry appears after an agent calls <code className="mx-1 font-mono">get_context</code>.
      </div>
    )
  }

  const width = 460
  const height = 128
  const padLeft = 40
  const padRight = 16
  const padTop = 26
  const padBottom = 18
  const plotW = width - padLeft - padRight
  const plotH = height - padTop - padBottom

  const maxVal = Math.max(budget, ...series.map((p) => p.tokens_used), 100)
  const midVal = Math.round(maxVal / 2)

  const coords = series.map((point, idx) => {
    const x =
      series.length === 1
        ? padLeft + plotW / 2
        : padLeft + (idx / (series.length - 1)) * plotW
    const ratio = Math.min(1, Math.max(0, point.tokens_used / maxVal))
    const y = padTop + plotH - ratio * plotH
    return { x, y, point }
  })

  // Smooth cubic spline path
  const pathD = coords.reduce((acc, cur, idx, arr) => {
    if (idx === 0) return `M ${cur.x.toFixed(1)} ${cur.y.toFixed(1)}`
    const prev = arr[idx - 1]
    const cx = ((prev.x + cur.x) / 2).toFixed(1)
    return `${acc} C ${cx} ${prev.y.toFixed(1)}, ${cx} ${cur.y.toFixed(1)}, ${cur.x.toFixed(1)} ${cur.y.toFixed(1)}`
  }, "")

  const baselineY = padTop + plotH
  const midY = padTop + plotH / 2
  const areaD =
    coords.length > 1
      ? `${pathD} L ${coords[coords.length - 1].x.toFixed(1)} ${baselineY.toFixed(1)} L ${coords[0].x.toFixed(1)} ${baselineY.toFixed(1)} Z`
      : ""
  const budgetY = padTop + plotH - (Math.min(budget, maxVal) / maxVal) * plotH
  const selectedIdx = activeIndex !== null && coords[activeIndex] ? activeIndex : coords.length - 1
  const selected = coords[selectedIdx]
  const tooltipX = Math.min(Math.max(selected.x, padLeft + 26), width - padRight - 26)
  const tooltipY = Math.max(4, selected.y - 26)

  return (
    <div className="w-full">
      <svg
        width="100%"
        height="132"
        viewBox={`0 0 ${width} ${height}`}
        className="overflow-visible text-foreground"
        role="img"
        aria-label="Token usage per context call"
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#c8eb5e" stopOpacity="0.26" />
            <stop offset="100%" stopColor="#c8eb5e" stopOpacity="0" />
          </linearGradient>
        </defs>

        <text x="4" y={padTop + 4} fill="currentColor" opacity="0.45" fontSize="10" className="font-mono">
          {maxVal}
        </text>
        <text
          x="4"
          y={midY + 3}
          fill="currentColor"
          opacity="0.45"
          fontSize="10"
          className="font-mono"
        >
          {midVal}
        </text>
        <text
          x="4"
          y={baselineY + 3}
          fill="currentColor"
          opacity="0.45"
          fontSize="10"
          className="font-mono"
        >
          0
        </text>

        <line
          x1={padLeft}
          y1={budgetY}
          x2={width - padRight}
          y2={budgetY}
          stroke="currentColor"
          strokeOpacity="0.14"
          strokeDasharray="4 4"
        />
        <line
          x1={padLeft}
          y1={midY}
          x2={width - padRight}
          y2={midY}
          stroke="currentColor"
          strokeOpacity="0.08"
          strokeDasharray="4 4"
        />
        <line
          x1={padLeft}
          y1={baselineY}
          x2={width - padRight}
          y2={baselineY}
          stroke="currentColor"
          strokeOpacity="0.1"
          strokeDasharray="4 4"
        />

        {coords.length > 1 ? (
          <>
            <path d={areaD} fill={`url(#${gradId})`} />
            <path d={pathD} fill="none" stroke="#c8eb5e" strokeWidth="2.2" strokeLinecap="round" />
          </>
        ) : null}

        {coords.map((item, idx) => {
          const isSelected = idx === selectedIdx
          return (
            <g
              key={item.point.id}
              className="cursor-pointer"
              onMouseEnter={() => setActiveIndex(idx)}
              onClick={() => setActiveIndex(idx)}
            >
              <circle cx={item.x} cy={item.y} r="10" fill="transparent" />
              <circle
                cx={item.x}
                cy={item.y}
                r={isSelected ? 4.5 : 3.5}
                fill={isSelected ? "#c8eb5e" : "var(--card)"}
                stroke="#c8eb5e"
                strokeWidth={isSelected ? 2 : 1.7}
              />
            </g>
          )
        })}

        <g transform={`translate(${tooltipX}, ${tooltipY})`}>
          <rect x="-24" y="-6" width="48" height="20" rx="6" fill="var(--primary)" />
          <text
            x="0"
            y="7"
            textAnchor="middle"
            fill="var(--primary-foreground)"
            fontSize="10"
            fontWeight="600"
            className="font-mono"
          >
            {selected.point.tokens_used}
          </text>
        </g>
      </svg>
      <div className="mt-1 flex items-center justify-between text-[11.5px] text-muted-foreground">
        <span>
          Call <span className="font-mono text-foreground">{selected.point.id}</span> ·{" "}
          {selected.point.persona || "task"} ({selected.point.client})
        </span>
        <span className="font-mono">
          {selected.point.tokens_used} / {selected.point.token_budget} tok
        </span>
      </div>
    </div>
  )
}

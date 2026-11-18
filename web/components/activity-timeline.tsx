"use client"

import Link from "next/link"

export type TimelineLane = {
  id: string
  label: string
  badge?: string
  href: string
  color: "lime" | "neutral" | "lavender"
  widthPct: number
  offsetPct: number
}

const COLORS = {
  lime: { outer: "rgba(200, 235, 94, 0.35)", inner: "#c8eb5e" },
  neutral: { outer: "rgba(197, 200, 208, 0.38)", inner: "#c5c8d0" },
  lavender: { outer: "rgba(165, 155, 243, 0.38)", inner: "#a59bf3" },
}

export function ActivityTimeline({ lanes }: { lanes: TimelineLane[] }) {
  const hours = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00"]

  return (
    <div className="relative flex flex-col gap-3 pt-2">
      <div className="grid grid-cols-8 pb-2.5 text-center text-[11px] text-muted-foreground">
        {hours.map((h) => (
          <span key={h}>{h}</span>
        ))}
      </div>

      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-[26px] bottom-0 left-[68%] z-10 w-[1.5px] bg-foreground"
      >
        <span className="absolute -top-1 -left-[3.2px] size-2 rounded-full bg-foreground" />
      </div>

      {lanes.map((lane) => {
        const palette = COLORS[lane.color]
        return (
          <Link
            key={lane.id}
            href={lane.href}
            className="flex items-center rounded-2xl p-1 transition-transform hover:translate-x-0.5"
            style={{
              width: `${lane.widthPct}%`,
              marginLeft: `${lane.offsetPct}%`,
              background: palette.outer,
            }}
          >
            <div
              className="flex w-full items-center justify-between gap-2 rounded-[13px] px-3.5 py-2 text-[12.5px] font-semibold text-[#141517]"
              style={{ background: palette.inner }}
            >
              <span className="truncate">{lane.label}</span>
              {lane.badge ? (
                <span className="shrink-0 rounded-full bg-[#18191d] px-2.5 py-0.5 text-[11px] font-semibold text-white">
                  {lane.badge}
                </span>
              ) : null}
            </div>
          </Link>
        )
      })}
    </div>
  )
}

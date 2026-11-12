import { Badge } from "@/components/ui/badge"
import type { GovernanceSummary } from "@/lib/api"

export function GovernanceBadges({ governance }: { governance?: GovernanceSummary }) {
  if (!governance) return null
  const severity = governance.highest_severity || "clean"
  const scanLabel =
    severity === "clean"
      ? "scan:clean"
      : `scan:${severity}`
  const scanVariant =
    severity === "critical" || severity === "high"
      ? "destructive"
      : severity === "medium"
        ? "outline"
        : "secondary"
  return (
    <span className="inline-flex flex-wrap gap-1">
      <Badge variant={scanVariant}>{scanLabel}</Badge>
      {governance.freshness === "aging" ? <Badge variant="outline">fresh:aging</Badge> : null}
      {governance.accepted_risk ? <Badge variant="outline">risk accepted</Badge> : null}
    </span>
  )
}

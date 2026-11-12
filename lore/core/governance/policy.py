"""Severity policy, scoring, and finding merge for governance scans."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from lore.core.governance.atr import Finding

BLOCKING = frozenset({"critical", "high"})

_SEVERITY_WEIGHT = {
    "critical": 40,
    "high": 25,
    "medium": 10,
    "low": 3,
}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def score_findings(findings: list[Finding] | list[dict[str, Any]]) -> int:
    total = 0
    for item in findings:
        severity = item.severity if isinstance(item, Finding) else str(item.get("severity", "low"))
        total += _SEVERITY_WEIGHT.get(severity.lower(), 1)
    return min(100, total)


def blocking_findings(findings: list[Finding] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for item in findings:
        data = item.as_dict() if isinstance(item, Finding) else dict(item)
        if str(data.get("severity", "")).lower() in BLOCKING:
            blocked.append(data)
    return blocked


def should_block(findings: list[Finding] | list[dict[str, Any]], *, accept_risk: bool) -> bool:
    if accept_risk:
        return False
    return bool(blocking_findings(findings))


def merge_findings(
    static: list[Finding],
    external: list[Finding],
) -> list[Finding]:
    """Prefer ATR/static ids; append SkillSpector-only findings."""
    merged: list[Finding] = list(static)
    seen = {(f.id, tuple(f.evidence)) for f in static}
    for item in external:
        key = (item.id, tuple(item.evidence))
        if key in seen:
            continue
        # Dedupe by overlapping category+line when SkillSpector echoes ATR shapes.
        overlap = False
        for existing in static:
            if existing.category == item.category and set(existing.evidence) & set(item.evidence):
                overlap = True
                break
        if overlap:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def scan_report(
    findings: list[Finding],
    *,
    tool: str,
    accepted_risk: bool = False,
    accepted_at: str | None = None,
    accepted_note: str | None = None,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "at": utc_now_iso(),
        "score": score_findings(findings),
        "findings": [f.as_dict() for f in findings],
        "accepted_risk": accepted_risk,
        "accepted_at": accepted_at,
        "accepted_note": accepted_note,
    }

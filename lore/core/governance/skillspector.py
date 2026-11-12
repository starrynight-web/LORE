"""Optional NVIDIA SkillSpector enrichment (static --no-llm only)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from lore.core.governance.atr import Finding

_TIMEOUT_SEC = 45

# Map common SkillSpector pattern ids onto our finding categories.
_CATEGORY_HINTS = {
    "P1": "P1",
    "P2": "P2",
    "P3": "P3",
    "P9": "P9",
    "PE3": "PE3",
    "SC2": "SC2",
    "E1": "P3",
    "E2": "PE3",
}


def skillspector_path() -> str | None:
    return shutil.which("skillspector")


def available() -> bool:
    return skillspector_path() is not None


def _severity_from_ss(raw: Any) -> str:
    text = str(raw or "medium").lower()
    if text in {"critical", "high", "medium", "low"}:
        return text
    if text in {"error", "fatal"}:
        return "critical"
    if text in {"warning", "warn"}:
        return "medium"
    if text in {"note", "info"}:
        return "low"
    return "medium"


def _findings_from_payload(payload: Any) -> list[Finding]:
    findings: list[Finding] = []
    rows: list[Any] = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for key in ("findings", "results", "issues", "violations"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                break
        if not rows and isinstance(payload.get("report"), dict):
            report = payload["report"]
            for key in ("findings", "results"):
                value = report.get(key)
                if isinstance(value, list):
                    rows = value
                    break
    for row in rows:
        if not isinstance(row, dict):
            continue
        rule_id = str(
            row.get("ruleId")
            or row.get("rule_id")
            or row.get("id")
            or row.get("pattern_id")
            or row.get("pattern")
            or "SKILLSPECTOR"
        )
        category = _CATEGORY_HINTS.get(rule_id, str(row.get("category") or rule_id))
        title = str(row.get("title") or row.get("message") or row.get("name") or rule_id)
        severity = _severity_from_ss(row.get("severity") or row.get("level"))
        evidence: list[str] = []
        loc = row.get("location") or row.get("locations") or {}
        if isinstance(loc, dict):
            path = loc.get("path") or loc.get("uri") or "skill"
            start = loc.get("startLine") or loc.get("line") or loc.get("start_line")
            if start is not None:
                evidence.append(f"{path}:{start}")
            else:
                evidence.append(str(path))
        elif isinstance(row.get("file"), str):
            line = row.get("line")
            evidence.append(f"{row['file']}:{line}" if line is not None else row["file"])
        if not evidence:
            evidence = ["skillspector"]
        findings.append(
            Finding(
                id=f"SS-{rule_id}",
                category=category,
                owasp="AST01",
                severity=severity,
                title=title,
                evidence=evidence,
                description=str(row.get("description") or ""),
                tool="skillspector",
            )
        )
    return findings


def scan_text(text: str, *, filename: str = "SKILL.md") -> list[Finding]:
    """Run SkillSpector when installed; return [] if missing or on failure."""
    binary = skillspector_path()
    if binary is None:
        return []
    with tempfile.TemporaryDirectory(prefix="lore-ss-") as tmp:
        root = Path(tmp)
        path = root / filename
        path.write_text(text, encoding="utf-8")
        report = root / "report.json"
        try:
            completed = subprocess.run(
                [
                    binary,
                    "scan",
                    str(path),
                    "--no-llm",
                    "--format",
                    "json",
                    "--output",
                    str(report),
                ],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SEC,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        payload: Any = None
        if report.is_file():
            try:
                payload = json.loads(report.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = None
        if payload is None and completed.stdout.strip():
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError:
                return []
        if payload is None:
            return []
        return _findings_from_payload(payload)

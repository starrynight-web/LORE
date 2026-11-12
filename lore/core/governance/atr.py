"""Load and run vendored Agent Threat Rule YAML against skill text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

RULES_DIR = Path(__file__).resolve().parent / "rules"

_FLAG_MAP = {
    "i": re.IGNORECASE,
    "m": re.MULTILINE,
    "s": re.DOTALL,
}


@dataclass(frozen=True)
class Finding:
    id: str
    category: str
    owasp: str
    severity: str
    title: str
    evidence: list[str]
    description: str = ""
    tool: str = "lore-static"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "owasp": self.owasp,
            "severity": self.severity,
            "title": self.title,
            "evidence": list(self.evidence),
            "description": self.description,
            "tool": self.tool,
        }


def _compile_flags(raw: str | None) -> int:
    flags = 0
    for ch in raw or "":
        flags |= _FLAG_MAP.get(ch.lower(), 0)
    return flags


def _line_for_span(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


@lru_cache(maxsize=1)
def load_rules() -> tuple[dict[str, Any], ...]:
    rules: list[dict[str, Any]] = []
    for path in sorted(RULES_DIR.glob("*.yaml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and loaded.get("id"):
            rules.append(loaded)
    return tuple(rules)


def scan_text(text: str, *, source: str = "body") -> list[Finding]:
    """Run all vendored rules against raw skill markdown (header + body)."""
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for rule in load_rules():
        detection = rule.get("detection") or {}
        conditions = detection.get("conditions") or []
        if not isinstance(conditions, list):
            continue
        rule_id = str(rule.get("id", ""))
        default_category = str(rule.get("category") or "P2")
        owasp = str(rule.get("owasp") or "AST01")
        severity = str(rule.get("severity") or "medium").lower()
        title = str(rule.get("title") or rule_id)
        matched = False
        evidence: list[str] = []
        matched_category = default_category
        matched_desc = ""
        for cond in conditions:
            if not isinstance(cond, dict):
                continue
            if str(cond.get("operator", "regex")).lower() != "regex":
                continue
            pattern = str(cond.get("value", ""))
            if not pattern:
                continue
            try:
                compiled = re.compile(pattern, _compile_flags(cond.get("flags")))
            except re.error:
                continue
            hit = compiled.search(text)
            if hit is None:
                continue
            matched = True
            line = _line_for_span(text, hit.start())
            evidence.append(f"{source}:{line}")
            matched_category = str(cond.get("category") or default_category)
            matched_desc = str(cond.get("description") or "")
            # ATR condition: any — one hit is enough per rule, keep collecting evidence
            # but stop after a few spans to keep reports small.
            if len(evidence) >= 3:
                break
        if not matched:
            continue
        key = (rule_id, evidence[0] if evidence else "")
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            Finding(
                id=rule_id,
                category=matched_category,
                owasp=owasp,
                severity=severity,
                title=title,
                evidence=evidence,
                description=matched_desc,
            )
        )
    return findings

"""Skill and persona governance: ATR scan, optional SkillSpector, freshness."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lore.core import personas
from lore.core.governance import skillspector
from lore.core.governance.atr import Finding
from lore.core.governance.atr import scan_text as atr_scan_text
from lore.core.governance.freshness import check_freshness
from lore.core.governance.policy import (
    merge_findings,
    scan_report,
    should_block,
    utc_now_iso,
)
from lore.core.okf import Doc, write_doc


class GovernanceBlock(Exception):
    """Approve is refused because of blocking scan findings."""

    def __init__(self, message: str, governance: dict[str, Any]) -> None:
        super().__init__(message)
        self.governance = governance
        self.message = message


def _doc_text(doc: Doc) -> str:
    """Raw text as the agent would see it (header fields + body)."""
    parts = [
        str(doc.get("title")),
        str(doc.get("summary")),
        str(doc.header.get("description") or ""),
        str(doc.header.get("when_to_use") or ""),
        doc.body or "",
    ]
    return "\n".join(parts)


def scan_skill(
    doc: Doc,
    *,
    use_skillspector: bool = True,
) -> dict[str, Any]:
    """Run built-in ATR scan and optional SkillSpector; return scan report dict."""
    text = _doc_text(doc)
    static = atr_scan_text(text, source=doc.path.name if doc.path else "body")
    external: list[Finding] = []
    tools = ["lore-static"]
    if use_skillspector and skillspector.available():
        external = skillspector.scan_text(text, filename=doc.path.name if doc.path else "SKILL.md")
        if external:
            tools.append("skillspector")
    findings = merge_findings(static, external)
    prior_raw = doc.header.get("governance")
    prior = prior_raw if isinstance(prior_raw, dict) else {}
    prior_scan_raw = prior.get("scan")
    prior_scan = prior_scan_raw if isinstance(prior_scan_raw, dict) else {}
    return scan_report(
        findings,
        tool="+".join(tools),
        accepted_risk=bool(prior_scan.get("accepted_risk")),
        accepted_at=prior_scan.get("accepted_at"),
        accepted_note=prior_scan.get("accepted_note"),
    )


def stamp_scan(doc: Doc, *, use_skillspector: bool = False) -> Doc:
    """Persist a non-blocking scan onto the document header and write if pathed."""
    scan = scan_skill(doc, use_skillspector=use_skillspector)
    gov_raw = doc.header.get("governance")
    gov = dict(gov_raw) if isinstance(gov_raw, dict) else {}
    gov["scan"] = scan
    if "freshness" not in gov:
        gov["freshness"] = check_freshness(doc, project=_project_for(doc), stamp=False)
    doc.header["governance"] = gov
    if doc.path is not None:
        write_doc(doc.path, doc)
    return doc


def _project_for(doc: Doc) -> Path | None:
    if doc.path is None:
        return None
    # .lore/skills/<persona>/file.md or .lore/personas/file.md
    for parent in doc.path.parents:
        if parent.name == ".lore":
            return parent.parent
    return doc.path.parent


def governance_summary(doc: Doc) -> dict[str, Any]:
    gov_raw = doc.header.get("governance")
    gov = gov_raw if isinstance(gov_raw, dict) else {}
    scan_raw = gov.get("scan")
    scan = scan_raw if isinstance(scan_raw, dict) else {}
    freshness_raw = gov.get("freshness")
    freshness = freshness_raw if isinstance(freshness_raw, dict) else {}
    findings_raw = scan.get("findings")
    findings = findings_raw if isinstance(findings_raw, list) else []
    highest = "clean"
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    best = 0
    for row in findings:
        if not isinstance(row, dict):
            continue
        level = order.get(str(row.get("severity", "")).lower(), 0)
        if level > best:
            best = level
            highest = str(row.get("severity", "")).lower()
    return {
        "score": scan.get("score", 0),
        "highest_severity": highest,
        "finding_count": len(findings),
        "freshness": freshness.get("status") or "current",
        "verified_at": freshness.get("verified_at"),
        "accepted_risk": bool(scan.get("accepted_risk")),
        "skillspector": "skillspector" in str(scan.get("tool") or ""),
        "tool": scan.get("tool") or "lore-static",
    }


def approve_item(
    project: Path,
    item_id: str,
    *,
    accept_risk: bool = False,
    accept_note: str = "",
    use_skillspector: bool = True,
) -> Doc:
    """Scan, optionally block, stamp governance, and set status to stable."""
    doc = personas.find_any(project, item_id)
    if doc is None or doc.path is None:
        raise FileNotFoundError(item_id)

    scan = scan_skill(doc, use_skillspector=use_skillspector)
    findings = [
        Finding(
            id=str(row.get("id", "")),
            category=str(row.get("category", "")),
            owasp=str(row.get("owasp", "AST01")),
            severity=str(row.get("severity", "low")),
            title=str(row.get("title", "")),
            evidence=list(row.get("evidence") or []),
            description=str(row.get("description") or ""),
            tool=str(row.get("tool") or "lore-static"),
        )
        for row in (scan.get("findings") or [])
        if isinstance(row, dict)
    ]

    freshness = check_freshness(doc, project=project, stamp=True)
    gov = {
        "scan": {
            **scan,
            "accepted_risk": bool(accept_risk),
            "accepted_at": utc_now_iso() if accept_risk else None,
            "accepted_note": accept_note.strip() or None if accept_risk else None,
        },
        "freshness": freshness,
    }

    if should_block(findings, accept_risk=accept_risk):
        raise GovernanceBlock(
            "This item has critical or high security findings. Fix them or approve with accept_risk.",
            {"scan": gov["scan"], "freshness": freshness},
        )

    doc.header["governance"] = gov
    doc.header["status"] = "stable"
    write_doc(doc.path, doc)
    return doc


def freshness_of(doc: Doc) -> str:
    """Return current|aging for serve envelope."""
    gov_raw = doc.header.get("governance")
    gov = gov_raw if isinstance(gov_raw, dict) else {}
    freshness_raw = gov.get("freshness")
    freshness = freshness_raw if isinstance(freshness_raw, dict) else {}
    status = str(freshness.get("status") or "")
    if status in {"current", "aging"}:
        return status
    # Hand-edited stable skills with no scan: soft-aging signal.
    if not gov.get("scan"):
        return "aging"
    return "current"


__all__ = [
    "GovernanceBlock",
    "approve_item",
    "check_freshness",
    "freshness_of",
    "governance_summary",
    "scan_skill",
    "skillspector",
    "stamp_scan",
]

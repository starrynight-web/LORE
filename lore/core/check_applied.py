"""Deterministic receipt check: cited skill ids must match what get_context served."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lore.core.decisions import append_outcome, read_decision


def check_applied(
    project: Path,
    decision_id: str,
    rule_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return pass, fail, or skip for citations against a decision's served ids."""
    cited = [str(item).strip() for item in (rule_ids or []) if str(item).strip()]
    doc = read_decision(project, decision_id)
    header = doc.header if isinstance(doc.header, dict) else {}
    included = header.get("included")
    served_raw: list[Any] = included if isinstance(included, list) else []
    served = {str(item) for item in served_raw if str(item).startswith("skill:")}

    if not served:
        status = "skip"
        detail = "Nothing to cite for this decision."
        unknown: list[str] = []
    else:
        unknown = sorted({item for item in cited if item not in served})
        if not cited:
            status = "fail"
            detail = "Citations required but none were provided."
        elif unknown:
            status = "fail"
            detail = "Cited ids were not served by this decision: " + ", ".join(unknown)
        else:
            status = "pass"
            detail = "Cited " + ", ".join(cited)
    detail = f"{detail} Citation receipt only; code changes are not verified."

    append_outcome(project, decision_id, f"check_applied: {status}", detail)
    return {
        "decision_id": decision_id,
        "check_kind": "citation_receipt",
        "code_verified": False,
        "status": status,
        "served": sorted(served),
        "cited": cited,
        "unknown": unknown,
        "missing": [],
        "summary": detail,
    }

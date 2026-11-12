"""CLI: lore-solo govern scan|check."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lore.core.governance import check_freshness, scan_skill, skillspector
from lore.core.okf import Doc, read_doc
from lore.core.paths import LoreNotFound, find_project
from lore.core.personas import find_any, list_personas, list_skill_files, locate_skill


def _project(start: Path | None = None) -> Path:
    try:
        return find_project(start or Path.cwd())
    except LoreNotFound as exc:
        raise SystemExit("No .lore folder found. Run lore-solo setup first.") from exc


def _iter_docs(project: Path, path: Path | None) -> list[Doc]:
    if path is not None:
        target = path if path.is_absolute() else project / path
        if target.is_file():
            return [read_doc(target)]
        found = locate_skill(project, path.name) or locate_skill(project, str(path))
        if found is not None:
            return [found[1]]
        doc = find_any(project, str(path))
        if doc is not None:
            return [doc]
        raise SystemExit(f"No skill or persona at {path}")
    docs = list(list_personas(project))
    docs.extend(doc for _p, doc in list_skill_files(project))
    return docs


def run_scan(argv: list[str]) -> int:
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    path = Path(args[0]) if args else None
    project = _project()
    docs = _iter_docs(project, path)
    rows = []
    worst = 0
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "clean": 0}
    for doc in docs:
        report = scan_skill(doc, use_skillspector=skillspector.available())
        findings = report.get("findings") or []
        highest = "clean"
        for row in findings:
            sev = str(row.get("severity", "")).lower()
            if order.get(sev, 0) > order.get(highest, 0):
                highest = sev
        worst = max(worst, order.get(highest, 0))
        rows.append(
            {
                "id": doc.get("id"),
                "score": report.get("score"),
                "highest": highest,
                "findings": findings,
                "tool": report.get("tool"),
            }
        )
    if as_json:
        print(json.dumps({"skillspector": skillspector.available(), "items": rows}, indent=2))
    else:
        print(f"SkillSpector: {'yes' if skillspector.available() else 'not on PATH'}")
        for row in rows:
            print(f"{row['id']}: {row['highest']} (score {row['score']}, tool {row['tool']})")
            row_findings = row["findings"]
            if not isinstance(row_findings, list):
                continue
            for finding in row_findings:
                if not isinstance(finding, dict):
                    continue
                evidence = finding.get("evidence")
                joined = ", ".join(evidence) if evidence else ""
                print(
                    f"  - [{finding.get('severity')}] {finding.get('id')} "
                    f"{finding.get('title')} @ {joined}"
                )
    return 1 if worst >= 3 else 0


def run_check(argv: list[str]) -> int:
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    path = Path(args[0]) if args else None
    project = _project()
    docs = _iter_docs(project, path)
    rows = []
    aging = 0
    for doc in docs:
        report = check_freshness(doc, project=project, stamp=False)
        if report.get("status") == "aging":
            aging += 1
        rows.append({"id": doc.get("id"), **report})
    if as_json:
        print(json.dumps({"items": rows}, indent=2))
    else:
        for row in rows:
            stale = ", ".join(row.get("claims_stale") or []) or "-"
            print(
                f"{row['id']}: {row['status']} "
                f"(ok={row['claims_ok']} stale={stale} unverifiable={row['claims_unverifiable']})"
            )
    return 0 if aging == 0 else 2


def run(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: lore-solo govern scan [path] [--json]\n"
            "       lore-solo govern check [path] [--json]",
            file=sys.stderr,
        )
        return 0
    command, rest = args[0], args[1:]
    if command == "scan":
        return run_scan(rest)
    if command == "check":
        return run_check(rest)
    print(f"unknown govern command {command!r}; use scan or check", file=sys.stderr)
    return 2

"""CLI: lore-solo persona list|show|create|update|approve|delete."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lore.core.governance import GovernanceBlock, approve_item, governance_summary
from lore.core.inbox import adopt_inbox
from lore.core.paths import LoreNotFound, find_project, library_root
from lore.core.personas import (
    delete_persona,
    find_persona,
    list_personas,
    list_skill_files,
    skill_belongs,
    update_persona,
    write_persona,
)


def _project(*, ensure: bool = False) -> Path:
    try:
        return find_project(Path.cwd())
    except LoreNotFound as exc:
        if ensure:
            lib = library_root()
            (lib / ".lore").mkdir(parents=True, exist_ok=True)
            return lib
        raise SystemExit("No .lore folder found. Run lore-solo setup first.") from exc


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def _cmd_list(args: argparse.Namespace) -> int:
    project = _project()
    rows = []
    for doc in list_personas(project):
        gov = governance_summary(doc)
        rows.append(
            {
                "id": doc.get("id"),
                "title": doc.get("title"),
                "status": doc.get("status"),
                "summary": doc.get("summary"),
                "skill_ids": doc.header.get("skill_ids") or [],
                "governance": gov,
            }
        )
    if args.json:
        _print_json({"personas": rows})
        return 0
    if not rows:
        print("No personas found.")
        return 0
    for row in rows:
        skills = row["skill_ids"]
        count = len(skills) if isinstance(skills, list) else 0
        print(f"{row['id']} [{row['status']}] ({count} skills) — {row['summary']}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    project = _project()
    doc = find_persona(project, args.persona_id)
    if doc is None:
        raise SystemExit(f"No persona {args.persona_id!r}.")
    skills = []
    for path, skill in list_skill_files(project):
        if skill_belongs(path, skill, doc.get("id")):
            skills.append(
                {
                    "id": skill.get("id"),
                    "title": skill.get("title"),
                    "status": skill.get("status"),
                    "summary": skill.get("summary"),
                    "governance": governance_summary(skill),
                }
            )
    payload = {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "status": doc.get("status"),
        "summary": doc.get("summary"),
        "body": doc.body,
        "governance": governance_summary(doc),
        "skills": skills,
    }
    if args.json:
        _print_json(payload)
        return 0
    print(f"{payload['id']} [{payload['status']}] — {payload['title']}")
    if payload["summary"]:
        print(f"Summary: {payload['summary']}")
    print(f"Skills ({len(skills)}):")
    for s in skills:
        print(f"  - {s['id']} [{s['status']}]")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    project = _project(ensure=True)
    doc = write_persona(
        project,
        args.name,
        summary=args.summary,
        body=args.body,
        title=args.title or args.name,
        status="draft",
    )
    if args.skill_ids:
        adopt_inbox(project, doc.get("id"), args.skill_ids)
        saved = find_persona(project, doc.get("id"))
        if saved is not None:
            doc = saved
    payload = {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "status": doc.get("status"),
        "summary": doc.get("summary"),
        "skill_ids": doc.header.get("skill_ids") or [],
        "governance": governance_summary(doc),
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Created draft persona {payload['id']}.")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    project = _project()
    try:
        doc = update_persona(
            project,
            args.persona_id,
            title=args.title,
            summary=args.summary,
            body=args.body,
            status=args.status,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"No persona {args.persona_id!r}.") from exc
    payload = {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "status": doc.get("status"),
        "summary": doc.get("summary"),
        "governance": governance_summary(doc),
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Updated {payload['id']} [{payload['status']}].")
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    project = _project()
    try:
        doc = approve_item(
            project,
            args.persona_id,
            accept_risk=args.accept_risk,
            accept_note=args.note,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"No persona {args.persona_id!r}.") from exc
    except GovernanceBlock as exc:
        if args.json:
            _print_json({"error": exc.message, "blocked": True, "governance": exc.governance})
        else:
            print(f"Blocked: {exc.message}", file=sys.stderr)
        return 1
    payload = {
        "id": doc.get("id"),
        "status": doc.get("status"),
        "governance": governance_summary(doc),
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Approved {payload['id']} -> {payload['status']}.")
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    project = _project()
    try:
        delete_persona(project, args.persona_id)
    except FileNotFoundError as exc:
        raise SystemExit(f"No persona {args.persona_id!r}.") from exc
    if args.json:
        _print_json({"removed": args.persona_id})
    else:
        print(f"Deleted {args.persona_id} (skills returned to inbox).")
    return 0


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lore-solo persona", description="Manage Lore personas.")
    sub = parser.add_subparsers(dest="action", required=True)

    p_list = sub.add_parser("list", help="List personas")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="Show one persona and its skills")
    p_show.add_argument("persona_id")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=_cmd_show)

    p_create = sub.add_parser("create", help="Create a draft persona")
    p_create.add_argument("name")
    p_create.add_argument("--title", default="")
    p_create.add_argument("--summary", default="")
    p_create.add_argument("--body", default="")
    p_create.add_argument("--skill", dest="skill_ids", action="append", default=[])
    p_create.add_argument("--json", action="store_true")
    p_create.set_defaults(func=_cmd_create)

    p_upd = sub.add_parser("update", help="Update a persona")
    p_upd.add_argument("persona_id")
    p_upd.add_argument("--title", default=None)
    p_upd.add_argument("--summary", default=None)
    p_upd.add_argument("--body", default=None)
    p_upd.add_argument("--status", default=None)
    p_upd.add_argument("--json", action="store_true")
    p_upd.set_defaults(func=_cmd_update)

    p_app = sub.add_parser("approve", help="Run governance and approve a persona")
    p_app.add_argument("persona_id")
    p_app.add_argument("--accept-risk", action="store_true")
    p_app.add_argument("--note", default="")
    p_app.add_argument("--json", action="store_true")
    p_app.set_defaults(func=_cmd_approve)

    p_del = sub.add_parser("delete", help="Delete a persona (returns skills to inbox)")
    p_del.add_argument("persona_id")
    p_del.add_argument("--json", action="store_true")
    p_del.set_defaults(func=_cmd_delete)

    args = parser.parse_args(argv)
    return int(args.func(args))

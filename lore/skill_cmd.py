"""CLI: lore-solo skill featured|search|install|add|inbox|adopt|list|create|approve|remove."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lore.core.governance import GovernanceBlock, approve_item, governance_summary
from lore.core.inbox import (
    add_from_folder,
    add_from_registry,
    add_text,
    adopt_inbox,
    featured_registry,
    list_inbox,
    remove_inbox,
    search_registry,
)
from lore.core.paths import LoreNotFound, find_project, library_root
from lore.core.personas import (
    delete_skill,
    file_slug,
    find_persona,
    persona_id,
    persona_slug,
    visible_skills,
    write_skill,
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


def _cmd_featured(args: argparse.Namespace) -> int:
    rows = featured_registry()
    if args.json:
        _print_json({"skills": rows})
        return 0
    for row in rows:
        print(f"{row['skill_id']} ({row['source']}) — {row['installs']} installs")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    rows = search_registry(args.query, limit=args.limit)
    if args.json:
        _print_json({"skills": rows})
        return 0
    if not rows:
        print("No skills matched.")
        return 0
    for row in rows:
        print(f"{row['skill_id']} ({row['source']}) — {row['installs']} installs")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    project = _project(ensure=True)
    saved = add_from_registry(project, args.source, args.skill_id)
    adopted: list[str] = []
    if args.persona:
        if find_persona(project, args.persona) is None:
            raise SystemExit(f"No persona {args.persona!r}.")
        adopted = adopt_inbox(project, persona_id(args.persona), [saved["id"]])
    if args.json:
        _print_json({"installed": saved, "adopted": adopted})
        return 0
    if adopted:
        print(f"Installed and filed under {persona_id(args.persona)}: {adopted[0]}")
    else:
        print(f"Installed to inbox: {saved['id']} ({saved['title']})")
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    project = _project(ensure=True)
    if args.folder:
        folder = Path(args.folder).expanduser().resolve()
        if not folder.is_dir():
            raise SystemExit(f"Not a directory: {folder}")
        saved = add_from_folder(project, folder)
        if args.json:
            _print_json({"skills": saved, "count": len(saved)})
        else:
            print(f"Imported {len(saved)} skill(s) into inbox.")
        return 0
    if args.file:
        path = Path(args.file).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"Not a file: {path}")
        content = path.read_text(encoding="utf-8")
        name = args.name or path.stem
        item = add_text(project, name, content)
    elif args.text is not None:
        item = add_text(project, args.name or "skill", args.text)
    else:
        raise SystemExit("Provide --folder, --file, or --text.")
    if args.json:
        _print_json(item)
    else:
        print(f"Added to inbox: {item['id']} ({item['title']})")
    return 0


def _cmd_inbox(args: argparse.Namespace) -> int:
    project = _project()
    rows = list_inbox(project)
    if args.json:
        _print_json({"skills": rows})
        return 0
    if not rows:
        print("Inbox is empty.")
        return 0
    for row in rows:
        print(f"{row['id']}: {row['title']} — {row['summary']}")
    return 0


def _cmd_adopt(args: argparse.Namespace) -> int:
    project = _project()
    if find_persona(project, args.persona) is None:
        raise SystemExit(f"No persona {args.persona!r}.")
    adopted = adopt_inbox(project, persona_id(args.persona), [args.skill_id])
    if not adopted:
        raise SystemExit(f"No waiting skill {args.skill_id!r} in inbox.")
    if args.json:
        _print_json({"id": adopted[0], "status": "draft", "persona": persona_id(args.persona)})
    else:
        print(f"Filed {adopted[0]} as draft under {persona_id(args.persona)}.")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    project = _project()
    wanted_slug = persona_slug(args.persona) if args.persona else ""
    rows = []
    for path, doc in visible_skills(project):
        if wanted_slug and path.parent.name != wanted_slug:
            continue
        gov = governance_summary(doc)
        rows.append(
            {
                "id": doc.get("id"),
                "title": doc.get("title"),
                "status": doc.get("status"),
                "persona": doc.get("persona"),
                "summary": doc.get("summary"),
                "governance": gov,
            }
        )
    if args.json:
        _print_json({"skills": rows})
        return 0
    if not rows:
        print("No skills found.")
        return 0
    for row in rows:
        gov_row = row["governance"]
        sev = gov_row["highest_severity"] if isinstance(gov_row, dict) else "clean"
        fresh = gov_row["freshness"] if isinstance(gov_row, dict) else "fresh"
        print(f"{row['id']} [{row['status']}] scan:{sev} fresh:{fresh} — {row['summary']}")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    project = _project(ensure=True)
    if find_persona(project, args.persona) is None:
        raise SystemExit(f"No persona {args.persona!r}.")
    body = args.body
    if not body and args.file:
        body = Path(args.file).expanduser().read_text(encoding="utf-8")
    doc = write_skill(
        project,
        persona_id(args.persona),
        file_slug(args.name),
        title=args.title or args.name,
        summary=args.summary,
        body=body,
        status="draft",
    )
    payload = {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "status": doc.get("status"),
        "persona": doc.get("persona"),
        "governance": governance_summary(doc),
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"Created draft skill {payload['id']}.")
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    project = _project()
    try:
        doc = approve_item(
            project,
            args.skill_id,
            accept_risk=args.accept_risk,
            accept_note=args.note,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"No skill {args.skill_id!r}.") from exc
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


def _cmd_remove(args: argparse.Namespace) -> int:
    project = _project()
    try:
        delete_skill(project, args.skill_id)
    except FileNotFoundError:
        remove_inbox(project, args.skill_id)
    if args.json:
        _print_json({"removed": args.skill_id})
    else:
        print(f"Removed {args.skill_id}.")
    return 0


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lore-solo skill", description="Manage Lore skills.")
    sub = parser.add_subparsers(dest="action", required=True)

    p_feat = sub.add_parser("featured", help="List featured skills from skills.sh")
    p_feat.add_argument("--json", action="store_true")
    p_feat.set_defaults(func=_cmd_featured)

    p_search = sub.add_parser("search", help="Search skills.sh")
    p_search.add_argument("query", nargs="?", default="")
    p_search.add_argument("--limit", type=int, default=50)
    p_search.add_argument("--json", action="store_true")
    p_search.set_defaults(func=_cmd_search)

    p_install = sub.add_parser("install", help="Install a skill from skills.sh")
    p_install.add_argument("source", help="GitHub owner/repo source")
    p_install.add_argument("skill_id", help="Skill ID in that source")
    p_install.add_argument("--persona", default="", help="Immediately adopt under this persona")
    p_install.add_argument("--json", action="store_true")
    p_install.set_defaults(func=_cmd_install)

    p_add = sub.add_parser("add", help="Add skill(s) from a folder, file, or text into inbox")
    p_add.add_argument("--folder", default="")
    p_add.add_argument("--file", default="")
    p_add.add_argument("--text", default=None)
    p_add.add_argument("--name", default="")
    p_add.add_argument("--json", action="store_true")
    p_add.set_defaults(func=_cmd_add)

    p_inbox = sub.add_parser("inbox", help="List waiting skills in inbox")
    p_inbox.add_argument("--json", action="store_true")
    p_inbox.set_defaults(func=_cmd_inbox)

    p_adopt = sub.add_parser("adopt", help="File an inbox skill under a persona")
    p_adopt.add_argument("skill_id")
    p_adopt.add_argument("--persona", required=True)
    p_adopt.add_argument("--json", action="store_true")
    p_adopt.set_defaults(func=_cmd_adopt)

    p_list = sub.add_parser("list", help="List skills in the store")
    p_list.add_argument("--persona", default="")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)

    p_create = sub.add_parser("create", help="Create a draft skill under a persona")
    p_create.add_argument("--persona", required=True)
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--title", default="")
    p_create.add_argument("--summary", default="")
    p_create.add_argument("--body", default="")
    p_create.add_argument("--file", default="")
    p_create.add_argument("--json", action="store_true")
    p_create.set_defaults(func=_cmd_create)

    p_approve = sub.add_parser("approve", help="Run governance and approve a skill")
    p_approve.add_argument("skill_id")
    p_approve.add_argument("--accept-risk", action="store_true")
    p_approve.add_argument("--note", default="")
    p_approve.add_argument("--json", action="store_true")
    p_approve.set_defaults(func=_cmd_approve)

    p_rm = sub.add_parser("remove", help="Remove a skill or inbox item")
    p_rm.add_argument("skill_id")
    p_rm.add_argument("--json", action="store_true")
    p_rm.set_defaults(func=_cmd_remove)

    args = parser.parse_args(argv)
    return int(args.func(args))

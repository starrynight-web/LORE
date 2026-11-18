"""MCP tools. The IDE starts this process. It does not open a port."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, cast

from fastmcp import FastMCP

from lore import container_paths
from lore.connect import MCP_SERVER_NAME
from lore.core.check_applied import check_applied as run_check_applied
from lore.core.check_applied import has_receipt
from lore.core.context import get_context as build_context
from lore.core.decisions import append_outcome, read_decision
from lore.core.governance import (
    GovernanceBlock,
    governance_summary,
    scan_skill,
    skillspector,
)
from lore.core.governance import approve_item as run_approve_item
from lore.core.governance import (
    check_freshness as run_freshness_check,
)
from lore.core.graph import locate as locate_files
from lore.core.graph import map_status as read_map_status
from lore.core.idempotency import recall, remember
from lore.core.inbox import (
    add_from_folder,
    add_from_registry,
    add_text,
    adopt_inbox,
    featured_registry,
    search_registry,
)
from lore.core.inbox import (
    list_inbox as read_inbox,
)
from lore.core.instructions import STANDING_INSTRUCTIONS
from lore.core.okf import Doc
from lore.core.paths import LoreNotFound, find_project, library_root, map_root, workspace_root
from lore.core.personas import (
    find_any,
    find_persona,
    find_skill,
    list_skill_files,
    locate_skill,
    persona_id,
    persona_slug,
    update_persona,
    visible_skills,
    write_persona,
    write_skill,
)
from lore.core.personas import list_personas as load_personas
from lore.core.usage import summary as usage_summary
from lore.setup.graph_job import start_build

CODING_TOOLS = frozenset(
    {"get_context", "get_skill", "map_codebase", "check_applied", "log_decision"}
)

SKILL_PAGE_MAX = 24000


def skill_page(doc: Doc, offset: int, limit: int) -> dict[str, Any]:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit < 1 or limit > SKILL_PAGE_MAX:
        raise ValueError(f"limit must be between 1 and {SKILL_PAGE_MAX}")
    body = doc.body or ""
    page = body[offset : offset + limit]
    end = offset + len(page)
    next_offset: int | None = None if end >= len(body) else end
    return {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "summary": doc.get("summary"),
        "body": page,
        "offset": offset,
        "next_offset": next_offset,
        "has_more": next_offset is not None,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def _resolve_docs(project: Path, item_id: str) -> list[Doc]:
    if not item_id.strip():
        docs = list(load_personas(project))
        docs.extend(doc for _p, doc in list_skill_files(project))
        return docs
    found = locate_skill(project, item_id)
    if found is not None:
        return [found[1]]
    doc = find_any(project, item_id)
    if doc is not None:
        return [doc]
    raise ValueError(f"No skill or persona {item_id!r}")


def resolve_surface(argv: list[str] | None = None) -> str:
    """Return `coding` (default) or `full` from env / argv."""
    args = list(argv or [])
    if "--full" in args:
        return "full"
    if "--coding" in args:
        return "coding"
    raw = os.environ.get("LORE_MCP_SURFACE", "").strip().lower()
    if raw in {"full", "coding"}:
        return raw
    return "coding"


def build(project: Path | None = None, surface: str | None = None) -> FastMCP:
    chosen = surface or resolve_surface()
    mcp = FastMCP(MCP_SERVER_NAME, instructions=STANDING_INSTRUCTIONS)

    def origin() -> Path:
        if project is not None:
            return project
        return workspace_root()

    def root() -> Path:
        return find_project(origin())

    def ensure_root() -> Path:
        try:
            return root()
        except LoreNotFound:
            lib = library_root()
            (lib / ".lore").mkdir(parents=True, exist_ok=True)
            return lib

    def maps() -> Path:
        return map_root(origin())

    @mcp.tool
    def get_context(intent: str = "", persona: str = "", file_path: str = "") -> dict[str, Any]:
        """Matching skill summaries and files. Call once per task."""
        result = build_context(
            origin(), persona, intent, container_paths.to_runtime(file_path)
        )
        return cast(dict[str, Any], container_paths.convert_result(result))

    @mcp.tool
    def get_skill(
        name: str = "",
        persona: str = "",
        offset: int = 0,
        limit: int = 12000,
        names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Full steps for one or more stable skills."""
        owner = persona or None
        project = root()
        if names is not None:
            if not names:
                raise ValueError("names must not be empty")
            if limit < 1 or limit > SKILL_PAGE_MAX:
                raise ValueError(f"limit must be between 1 and {SKILL_PAGE_MAX}")
            total_budget = SKILL_PAGE_MAX if limit == 12000 else limit
            per_limit = max(1, total_budget // len(names))
            skills: list[dict[str, Any]] = []
            for item in names:
                doc = find_skill(project, item, owner)
                if doc is None:
                    raise ValueError(f"{item} is not a stable skill for this persona")
                skills.append(skill_page(doc, offset, per_limit))
            return {"skills": skills, "count": len(skills)}
        if not name.strip():
            raise ValueError("Provide name or names")
        doc = find_skill(project, name, owner)
        if doc is None:
            raise ValueError(f"{name} is not a stable skill for this persona")
        return skill_page(doc, offset, limit)

    @mcp.tool
    def map_codebase() -> dict[str, Any]:
        """Start the codebase map; returns while it runs."""
        return start_build(maps(), force=True)

    @mcp.tool
    def check_applied(decision_id: str, rule_ids: list[str] | None = None) -> dict[str, Any]:
        """Confirm cited skill ids were served by that get_context decision."""
        return run_check_applied(root(), decision_id, rule_ids)

    @mcp.tool
    def log_decision(
        decision_id: str,
        outcome: str,
        rule_ids: list[str] | None = None,
        note: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Verify cited skill ids and append an outcome receipt to a decision."""
        project = root()
        if idempotency_key:
            previous = recall(project, idempotency_key)
            if previous is not None:
                return {
                    **previous,
                    "decision_id": str(previous.get("decision_id", decision_id)),
                    "status": "already_recorded",
                }
        doc = read_decision(project, decision_id)
        receipt: dict[str, Any] | None = None
        if not has_receipt(doc):
            receipt = run_check_applied(project, decision_id, rule_ids)
        detail = note
        if rule_ids:
            cited = "Cited: " + ", ".join(rule_ids)
            detail = f"{note}\n{cited}".strip()
        append_outcome(project, decision_id, outcome, detail)
        payload: dict[str, Any] = {
            "decision_id": decision_id,
            "status": "recorded",
        }
        if receipt is not None:
            payload.update(
                {
                    "check_applied": receipt["status"],
                    "served": receipt["served"],
                    "cited": receipt["cited"],
                    "unknown": receipt["unknown"],
                }
            )
        remember(project, idempotency_key, payload)
        return payload

    if chosen == "full":

        @mcp.tool
        def list_personas(include_drafts: bool = False) -> list[dict[str, Any]]:
            """Persona names, status, and summaries (set include_drafts=True for drafts)."""
            rows: list[dict[str, Any]] = []
            for doc in load_personas(root()):
                status = doc.get("status")
                if not include_drafts and status != "stable":
                    continue
                rows.append(
                    {
                        "id": doc.get("id"),
                        "title": doc.get("title"),
                        "status": status,
                        "summary": doc.get("summary"),
                        "skill_ids": doc.header.get("skill_ids") or [],
                        "governance": governance_summary(doc),
                    }
                )
            return rows

        @mcp.tool
        def search_skills(query: str = "", limit: int = 25) -> dict[str, Any]:
            """Search skills.sh registry, or return featured skills when query is empty."""
            if not query.strip():
                rows = featured_registry()
                return {"skills": rows[:limit], "count": len(rows[:limit])}
            rows = search_registry(query.strip(), limit=limit)
            return {"skills": rows, "count": len(rows)}

        @mcp.tool
        def install_skill(
            source: str = "",
            skill_id: str = "",
            folder: str = "",
            name: str = "",
            content: str = "",
            persona: str = "",
        ) -> dict[str, Any]:
            """Install a skill from skills.sh (source+skill_id), folder, or raw text; optionally adopt into persona."""
            project_dir = ensure_root()
            installed: list[dict[str, str]] = []
            if source and skill_id:
                installed = [add_from_registry(project_dir, source, skill_id)]
            elif folder:
                target = Path(folder).expanduser().resolve()
                if not target.is_dir():
                    raise ValueError(f"Not a directory: {folder}")
                installed = add_from_folder(project_dir, target)
            elif content.strip():
                installed = [add_text(project_dir, name or "skill", content)]
            else:
                raise ValueError("Provide (source and skill_id), folder, or content.")

            adopted: list[str] = []
            if persona.strip():
                if find_persona(project_dir, persona) is None:
                    raise ValueError(f"No persona {persona!r}. Create it with setup_persona first.")
                ids = [item["id"] for item in installed if "id" in item]
                adopted = adopt_inbox(project_dir, persona_id(persona), ids)
            return {"installed": installed, "adopted": adopted}

        @mcp.tool
        def list_inbox() -> dict[str, Any]:
            """List waiting skills in the inbox."""
            rows = read_inbox(root())
            return {"skills": rows, "count": len(rows)}

        @mcp.tool
        def list_skills(persona: str = "", include_drafts: bool = True) -> dict[str, Any]:
            """List skills with status, governance, and freshness metadata."""
            project_dir = root()
            wanted = persona_slug(persona) if persona.strip() else ""
            rows: list[dict[str, Any]] = []
            for path, doc in visible_skills(project_dir):
                if wanted and path.parent.name != wanted:
                    continue
                if not include_drafts and doc.get("status") != "stable":
                    continue
                rows.append(
                    {
                        "id": doc.get("id"),
                        "title": doc.get("title"),
                        "status": doc.get("status"),
                        "persona": doc.get("persona"),
                        "summary": doc.get("summary"),
                        "governance": governance_summary(doc),
                    }
                )
            return {"skills": rows, "count": len(rows)}

        @mcp.tool
        def setup_persona(
            name: str,
            summary: str = "",
            body: str = "",
            title: str = "",
            skill_ids: list[str] | None = None,
            approve: bool = False,
            accept_risk: bool = False,
            note: str = "",
        ) -> dict[str, Any]:
            """Create or update a persona, optionally adopt inbox skills, and optionally approve it."""
            project_dir = ensure_root()
            existing = find_persona(project_dir, name)
            if existing is None:
                doc = write_persona(
                    project_dir,
                    name,
                    summary=summary,
                    body=body,
                    title=title or name,
                    status="draft",
                )
            else:
                doc = update_persona(
                    project_dir,
                    name,
                    title=title or None,
                    summary=summary or None,
                    body=body or None,
                )
            adopted: list[str] = []
            if skill_ids:
                adopted = adopt_inbox(project_dir, doc.get("id"), skill_ids)
                refreshed = find_persona(project_dir, doc.get("id"))
                if refreshed is not None:
                    doc = refreshed
            blocked = False
            block_error = ""
            if approve:
                try:
                    doc = run_approve_item(
                        project_dir,
                        doc.get("id"),
                        accept_risk=accept_risk,
                        accept_note=note,
                    )
                except GovernanceBlock as exc:
                    blocked = True
                    block_error = exc.message
            return {
                "id": doc.get("id"),
                "title": doc.get("title"),
                "status": doc.get("status"),
                "adopted": adopted,
                "blocked": blocked,
                **({"error": block_error} if block_error else {}),
                "governance": governance_summary(doc),
            }

        @mcp.tool
        def approve_item(
            item_id: str,
            accept_risk: bool = False,
            note: str = "",
        ) -> dict[str, Any]:
            """Run ATR/SkillSpector scan + freshness check and approve a draft skill or persona."""
            project_dir = root()
            try:
                doc = run_approve_item(
                    project_dir,
                    item_id,
                    accept_risk=accept_risk,
                    accept_note=note,
                )
            except GovernanceBlock as exc:
                return {
                    "id": item_id,
                    "approved": False,
                    "blocked": True,
                    "error": exc.message,
                    "governance": exc.governance,
                }
            return {
                "id": doc.get("id"),
                "approved": True,
                "blocked": False,
                "status": doc.get("status"),
                "governance": governance_summary(doc),
            }

        @mcp.tool
        def check_security(item_id: str = "") -> dict[str, Any]:
            """Run ATR + optional SkillSpector security scan on one item or the whole store."""
            project_dir = root()
            docs = _resolve_docs(project_dir, item_id)
            items = []
            for doc in docs:
                report = scan_skill(doc, use_skillspector=skillspector.available())
                findings = report.get("findings") or []
                items.append(
                    {
                        "id": doc.get("id"),
                        "score": report.get("score"),
                        "tool": report.get("tool"),
                        "findings": findings,
                    }
                )
            return {"skillspector": skillspector.available(), "items": items}

        @mcp.tool
        def check_freshness(item_id: str = "") -> dict[str, Any]:
            """Check freshness and cited repo claims for one item or the whole store."""
            project_dir = root()
            docs = _resolve_docs(project_dir, item_id)
            items = []
            for doc in docs:
                report = run_freshness_check(doc, project=project_dir, stamp=False)
                items.append({"id": doc.get("id"), **report})
            return {"items": items}

        @mcp.tool
        def get_telemetry() -> dict[str, Any]:
            """Return call counts, token usage telemetry, and top agents/personas/skills."""
            return cast(dict[str, Any], usage_summary(root()))

        @mcp.tool
        def ingest(
            persona: str,
            filename: str,
            content: str,
            title: str = "",
            summary: str = "",
            idempotency_key: str = "",
        ) -> dict[str, Any]:
            """Save a skill draft until approved."""
            project = root()
            if idempotency_key:
                previous = recall(project, idempotency_key)
                if previous is not None:
                    return previous
            doc = write_skill(
                project,
                persona_id(persona),
                filename,
                title=title or filename,
                summary=summary,
                body=content,
                status="draft",
            )
            payload = {"id": doc.get("id"), "status": "draft"}
            remember(project, idempotency_key, payload)
            return payload

        @mcp.tool
        def trace(decision_id: str) -> dict[str, Any]:
            """Read one decision record."""
            doc = read_decision(root(), decision_id)
            return {"id": doc.get("id"), "header": doc.header, "body": doc.body}

        @mcp.tool
        def map_status() -> dict[str, Any]:
            """Map state: missing, running, ready, or failed."""
            return read_map_status(maps())

        @mcp.tool
        def locate(intent: str, file_path: str = "") -> dict[str, Any]:
            """Files for a task; get_context already includes them."""
            result = locate_files(
                maps(), intent, container_paths.to_runtime(file_path)
            )
            return cast(dict[str, Any], container_paths.convert_result(result))

    return mcp


def run(argv: list[str] | None = None) -> None:
    build(surface=resolve_surface(argv)).run(transport="stdio", show_banner=False)

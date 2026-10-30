"""MCP tools. The IDE starts this process. It does not open a port."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from lore.core.context import get_context as build_context
from lore.core.decisions import append_outcome, read_decision
from lore.core.graph import locate as locate_files
from lore.core.graph import map_status as read_map_status
from lore.core.idempotency import recall, remember
from lore.core.instructions import STANDING_INSTRUCTIONS
from lore.core.paths import find_project, map_root
from lore.core.personas import find_skill, persona_id, write_skill
from lore.core.personas import list_personas as load_personas
from lore.setup.graph_job import start_build


def build(project: Path | None = None) -> FastMCP:
    mcp = FastMCP("lore", instructions=STANDING_INSTRUCTIONS)

    def origin() -> Path:
        if project is not None:
            return project
        return Path.cwd()

    def root() -> Path:
        return find_project(origin())

    def maps() -> Path:
        return map_root(origin())

    @mcp.tool
    def get_context(intent: str = "", persona: str = "", file_path: str = "") -> dict[str, Any]:
        """Matching skill summaries and the files to open. Call once per task."""
        return build_context(origin(), persona, intent, file_path)

    @mcp.tool
    def get_skill(name: str, persona: str = "") -> dict[str, Any]:
        """Full steps for one stable skill."""
        owner = persona or None
        doc = find_skill(root(), name, owner)
        if doc is None:
            raise ValueError(f"{name} is not a stable skill for this persona")
        return {
            "id": doc.get("id"),
            "title": doc.get("title"),
            "summary": doc.get("summary"),
            "body": doc.body,
        }

    @mcp.tool
    def list_personas() -> list[dict[str, str]]:
        """Stable persona names."""
        rows = []
        for doc in load_personas(root()):
            if doc.get("status") != "stable":
                continue
            rows.append(
                {"id": doc.get("id"), "title": doc.get("title"), "summary": doc.get("summary")}
            )
        return rows

    @mcp.tool
    def ingest(
        persona: str,
        filename: str,
        content: str,
        title: str = "",
        summary: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Save a skill draft. It is not served until approved."""
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
    def log_decision(
        decision_id: str,
        outcome: str,
        rule_ids: list[str] | None = None,
        note: str = "",
        idempotency_key: str = "",
    ) -> dict[str, str]:
        """Append an outcome to a decision."""
        project = root()
        if idempotency_key:
            previous = recall(project, idempotency_key)
            if previous is not None:
                return {
                    "decision_id": str(previous.get("decision_id", decision_id)),
                    "status": "already_recorded",
                }
        detail = note
        if rule_ids:
            cited = "Cited: " + ", ".join(rule_ids)
            detail = f"{note}\n{cited}".strip()
        append_outcome(project, decision_id, outcome, detail)
        payload = {"decision_id": decision_id, "status": "recorded"}
        remember(project, idempotency_key, payload)
        return payload

    @mcp.tool
    def trace(decision_id: str) -> dict[str, Any]:
        """Read one decision."""
        doc = read_decision(root(), decision_id)
        return {"id": doc.get("id"), "header": doc.header, "body": doc.body}

    @mcp.tool
    def map_codebase() -> dict[str, Any]:
        """Start the codebase map. Returns while it runs."""
        return start_build(maps())

    @mcp.tool
    def map_status() -> dict[str, Any]:
        """Map state: missing, running, ready, or failed."""
        return read_map_status(maps())

    @mcp.tool
    def locate(intent: str, file_path: str = "") -> dict[str, Any]:
        """Files for a task. get_context already includes them."""
        return locate_files(maps(), intent, file_path)

    return mcp


def run(_argv: list[str] | None = None) -> None:
    build().run(transport="stdio", show_banner=False)

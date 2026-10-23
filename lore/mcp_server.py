"""MCP tools. The IDE starts this process. It does not open a port."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from lore.core.context import get_context as build_context
from lore.core.decisions import append_outcome, read_decision
from lore.core.idempotency import recall, remember
from lore.core.paths import find_project
from lore.core.personas import find_skill, persona_id, write_skill
from lore.core.personas import list_personas as load_personas


def build(project: Path | None = None) -> FastMCP:
    mcp = FastMCP("lore")

    def root() -> Path:
        if project is not None:
            return project
        return find_project(Path.cwd())

    @mcp.tool
    def get_context(persona: str, intent: str = "", file_path: str = "") -> dict[str, Any]:
        """Return one persona's skill summaries and a short codebase-map slice."""
        return build_context(root(), persona, intent, file_path)

    @mcp.tool
    def get_skill(name: str, persona: str = "") -> dict[str, Any]:
        """Return the full steps for one stable skill."""
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
        """List stable personas. Drafts are omitted."""
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
        """Save a skill as a draft. It is not served until a person approves it."""
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
        """Append what the agent did to an existing decision."""
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
        """Read one decision file."""
        doc = read_decision(root(), decision_id)
        return {"id": doc.get("id"), "header": doc.header, "body": doc.body}

    return mcp


def run(_argv: list[str] | None = None) -> None:
    build().run(transport="stdio", show_banner=False)

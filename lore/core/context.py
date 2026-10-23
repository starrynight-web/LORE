"""Build the `get_context` answer from files in `.lore/`."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from lore.core.budget import count_tokens
from lore.core.config import load_config
from lore.core.decisions import allocate
from lore.core.okf import Doc
from lore.core.paths import find_project
from lore.core.personas import find_persona, persona_id, served_skills


def get_context(
    start: Path,
    persona: str,
    intent: str = "",
    file_path: str = "",
) -> dict[str, Any]:
    """Answer for one persona. `file_path` is used once a codebase map exists."""
    project = find_project(start)
    config = load_config(project / ".lore")
    limit = config["token_budget"]
    max_items = config["max_items"]
    wanted = persona_id(persona)
    doc = find_persona(project, persona)
    graph_notes: list[str] = []
    graph_items = _graph_items(project, file_path, graph_notes)

    if doc is None:
        summary = f"No persona named {wanted}. Nothing governed applies."
        return _finish(
            project,
            persona=wanted,
            intent=intent,
            file_path=file_path,
            verdict="no_knowledge",
            directive="proceed",
            summary=summary,
            items=[],
            omitted=[],
            drafts=0,
            limit=limit,
            graph_notes=graph_notes,
        )

    if doc.get("status") != "stable":
        summary = f"{wanted} is still a draft. Approve it in Lore setup before using it."
        return _finish(
            project,
            persona=wanted,
            intent=intent,
            file_path=file_path,
            verdict="abstain",
            directive="ask_user",
            summary=summary,
            items=[],
            omitted=[],
            drafts=1,
            limit=limit,
            graph_notes=graph_notes,
        )

    skills = served_skills(project, wanted)
    drafts = _draft_count(project, wanted)
    summary = doc.get("summary") or doc.get("title") or wanted
    items, omitted, used = _fit(summary, skills, graph_items, limit, max_items)
    if omitted:
        summary = f"{summary} Left out because of the size cap: {', '.join(omitted)}."
    if not items:
        summary = f"{wanted} is stable and has no skills to apply."
        if graph_notes:
            summary = f"{summary} {' '.join(graph_notes)}"
        return _finish(
            project,
            persona=wanted,
            intent=intent,
            file_path=file_path,
            verdict="no_knowledge",
            directive="proceed",
            summary=summary,
            items=[],
            omitted=omitted,
            drafts=drafts,
            limit=limit,
            graph_notes=graph_notes,
        )

    if graph_notes:
        summary = f"{summary} {' '.join(graph_notes)}"
    return _finish(
        project,
        persona=wanted,
        intent=intent,
        file_path=file_path,
        verdict="ok",
        directive="proceed_and_cite",
        summary=summary,
        items=items,
        omitted=omitted,
        drafts=drafts,
        limit=limit,
        graph_notes=graph_notes,
        used=used,
    )


def _graph_items(project: Path, file_path: str, notes: list[str]) -> list[dict[str, Any]]:
    try:
        from lore.core.graph import slice_for
    except ImportError:
        return []
    return slice_for(project, file_path, notes)


def _fit(
    summary: str,
    skills: list[Doc],
    graph_items: list[dict[str, Any]],
    limit: int,
    max_items: int,
) -> tuple[list[dict[str, Any]], list[str], int]:
    items: list[dict[str, Any]] = []
    omitted: list[str] = []
    used = count_tokens(summary)
    pending: list[tuple[str, dict[str, Any]]] = []
    for doc in skills:
        pending.append((doc.get("id"), _skill_item(doc)))
    for item in graph_items:
        pending.append((str(item["id"]), item))
    for ident, item in pending:
        if len(items) >= max_items:
            omitted.append(ident)
            continue
        piece = f"{item.get('title', '')}\n{item['text']}"
        cost = count_tokens(piece)
        if used + cost > limit:
            omitted.append(ident)
            continue
        items.append(item)
        used += cost
    return items, omitted, used


def _skill_item(doc: Doc) -> dict[str, Any]:
    path = ""
    if doc.path is not None:
        path = doc.path.as_posix()
    return {
        "id": doc.get("id"),
        "kind": "skill",
        "role": "applies",
        "authority": "reviewed",
        "status": "stable",
        "freshness": "current",
        "origin": "human_authored",
        "confidence": {"band": "high", "p": 0.92},
        "title": doc.get("title"),
        "text": doc.get("summary"),
        "source": {"path": path, "anchor": "summary"},
    }


def _draft_count(project: Path, persona: str) -> int:
    from lore.core.personas import list_skill_files, skill_belongs

    count = 0
    for path, doc in list_skill_files(project):
        if skill_belongs(path, doc, persona) and doc.get("status") != "stable":
            count += 1
    return count


def _finish(
    project: Path,
    *,
    persona: str,
    intent: str,
    file_path: str,
    verdict: str,
    directive: str,
    summary: str,
    items: list[dict[str, Any]],
    omitted: list[str],
    drafts: int,
    limit: int,
    graph_notes: list[str],
    used: int | None = None,
) -> dict[str, Any]:
    if used is None:
        used = count_tokens(summary)
    included = [str(item["id"]) for item in items]
    record = allocate(
        project,
        {
            "tool": "get_context",
            "verdict": verdict,
            "directive": directive,
            "persona": persona,
            "included": included,
            "omitted": omitted,
        },
        summary + "\n",
    )
    task: dict[str, str] = {}
    if file_path:
        task["file"] = file_path
    if intent:
        task["intent"] = intent
    envelope: dict[str, Any] = {
        "schema": "lore.result/1",
        "decision_id": record.get("id"),
        "tool": "get_context",
        "verdict": verdict,
        "directive": directive,
        "summary": summary,
        "items": items,
        "conflicts": [],
        "violations": [],
        "excluded": {
            "superseded": 0,
            "draft": drafts,
            "quarantine": 0,
            "out_of_scope": 0,
            "stale": 0,
            "low_confidence": 0,
            "denied": 0,
        },
        "budget": {"limit": limit, "used": used},
        "links": [f"lore://personas/{persona.split(':', 1)[-1]}"]
        + [f"lore://skills/{str(item['id']).removeprefix('skill:')}" for item in items if item["kind"] == "skill"],
        "data": {"persona": persona, "omitted": omitted, "graph_notes": graph_notes},
        "as_of": date.today().isoformat(),
        "constants": {
            "abstain_band": [0.45, 0.55],
            "conflict_min_conf": 0.70,
            "token_budget": limit,
            "confidence_mode": "deterministic",
        },
    }
    if task:
        envelope["task"] = task
    return envelope

"""Build the `get_context` answer from files in `.lore/`."""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from lore.core.budget import count_tokens
from lore.core.config import load_config
from lore.core.decisions import allocate
from lore.core.okf import Doc
from lore.core.paths import find_project, map_root
from lore.core.personas import find_persona, list_personas, persona_id, persona_slug, served_skills

# Words that appear in almost every task sentence and would match every skill.
_STOP = frozenset(
    {
        "about",
        "after",
        "before",
        "change",
        "changed",
        "does",
        "done",
        "each",
        "edit",
        "file",
        "files",
        "from",
        "have",
        "into",
        "keep",
        "only",
        "order",
        "step",
        "steps",
        "still",
        "text",
        "that",
        "them",
        "then",
        "than",
        "the",
        "and",
        "for",
        "are",
        "was",
        "were",
        "these",
        "this",
        "those",
        "when",
        "will",
        "with",
        "would",
        "write",
        "your",
    }
)
# Shared role words. A persona matches on its distinctive name, not on "engineer" alone.
_ROLE = frozenset({"agent", "developer", "engineer"})

# Path tokens that hint which persona fits when the task sentence names no role.
_PATH_HINTS: dict[str, frozenset[str]] = {
    "frontend": frozenset(
        {
            "tsx",
            "jsx",
            "css",
            "scss",
            "html",
            "svelte",
            "vue",
            "components",
            "component",
            "ui",
            "button",
            "panel",
            "layout",
            "styles",
            "tailwind",
            "react",
        }
    ),
    "backend": frozenset(
        {
            "py",
            "go",
            "rs",
            "java",
            "kt",
            "php",
            "rb",
            "api",
            "server",
            "sql",
            "db",
            "migration",
            "migrations",
            "schema",
            "handler",
            "routes",
        }
    ),
    "accessibility": frozenset(
        {
            "a11y",
            "aria",
            "label",
            "accessible",
            "screenreader",
        }
    ),
}

# Expand short task words into related tokens so routing is not pure string equality.
_ALIASES: dict[str, frozenset[str]] = {
    "a11y": frozenset({"accessibility", "accessible", "aria", "label"}),
    "accessibility": frozenset({"a11y", "accessible", "aria", "label"}),
    "accessible": frozenset({"a11y", "accessibility", "aria", "label"}),
    "api": frozenset({"backend", "endpoint", "health", "status", "server"}),
    "backend": frozenset({"api", "server", "endpoint", "health"}),
    "frontend": frozenset({"ui", "panel", "button", "component", "react"}),
    "ui": frozenset({"frontend", "panel", "button", "component"}),
    "panel": frozenset({"frontend", "ui", "button", "component"}),
    "button": frozenset({"frontend", "ui", "label", "accessible"}),
    "label": frozenset({"a11y", "accessibility", "accessible", "aria", "button"}),
    "health": frozenset({"api", "backend", "status", "endpoint"}),
    "status": frozenset({"api", "backend", "health", "ready"}),
    "review": frozenset({"reviewer", "security", "guidelines"}),
}


def get_context(
    start: Path,
    persona: str,
    intent: str = "",
    file_path: str = "",
) -> dict[str, Any]:
    """Answer for one persona, or for a whole task when `persona` is empty.

    A task call picks the personas named by the sentence, returns only the skill
    summaries that share a word with it, and includes the files to open.
    """
    if not persona.strip():
        return _for_task(start, intent, file_path)
    project = find_project(start)
    maps = map_root(start)
    config = load_config(project / ".lore")
    limit = config["token_budget"]
    max_items = config["max_items"]
    wanted = persona_id(persona)
    doc = find_persona(project, persona)
    graph_notes: list[str] = []
    graph_items = _graph_items(maps, file_path, graph_notes)
    _refresh_map(maps, graph_notes)

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


def _for_task(start: Path, intent: str, file_path: str) -> dict[str, Any]:
    project = find_project(start)
    maps = map_root(start)
    config = load_config(project / ".lore")
    limit = config["token_budget"]
    max_items = config["max_items"]
    graph_notes: list[str] = []
    _refresh_map(maps, graph_notes)
    from lore.core.graph import locate

    found = locate(maps, intent, file_path)
    files = found.get("files") if isinstance(found, dict) else []
    if not isinstance(files, list):
        files = []
    paths = [str(item.get("path")) for item in files if isinstance(item, dict) and item.get("path")]
    words = _query_tokens(intent)
    # Path hints come from the explicit file_path only, not locate hits, so a
    # weak intent cannot pin a persona through incidental map matches.
    path_words = _expand(_path_tokens(file_path, []))
    chosen: list[Doc] = []
    personas: list[str] = []
    drafts = 0
    stable: list[tuple[str, Doc]] = []
    scored_personas: list[tuple[int, str]] = []
    for doc in list_personas(project):
        name = str(doc.get("id") or "")
        distinctive = _persona_tokens(doc, name) - _ROLE
        if doc.get("status") != "stable":
            if words and distinctive & words:
                drafts += 1
            continue
        stable.append((name, doc))
        score = _overlap_score(distinctive, words)
        if score:
            scored_personas.append((score, name))

    listed_all = False
    if scored_personas:
        scored_personas.sort(key=lambda row: (-row[0], row[1]))
        personas = [name for _score, name in scored_personas]
    elif stable:
        hinted = _personas_from_path_hints(stable, path_words)
        if hinted:
            personas = hinted
        else:
            personas = [name for name, _doc in stable]
            listed_all = True

    # When we only listed every persona as a fallback, require a real skill hit
    # against the raw intent (not alias expansion alone) so weak sentences stay
    # ok_with_notes instead of pulling random skills.
    skill_query = words or path_words
    strict_query = _tokens(intent) or path_words
    ranked: list[tuple[int, str, Doc]] = []
    for name in personas:
        for skill in served_skills(project, name):
            hay = _skill_tokens(skill)
            if listed_all:
                score = _overlap_score(hay, strict_query) if strict_query else 0
            else:
                score = _overlap_score(hay, skill_query) if skill_query else 0
            if score:
                ranked.append((score, str(skill.get("id") or ""), skill))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    chosen = [skill for _score, _ident, skill in ranked]

    if not personas and not paths:
        summary = "No persona or file matched this task."
        if graph_notes:
            summary = f"{summary} {' '.join(graph_notes)}"
        return _finish(
            project,
            persona="task",
            intent=intent,
            file_path=file_path,
            verdict="no_knowledge",
            directive="proceed",
            summary=summary,
            items=[],
            omitted=[],
            drafts=drafts,
            limit=limit,
            graph_notes=graph_notes,
            files=files,
            personas=personas,
        )

    items, omitted, used = _fit("", chosen, [], limit, max_items)
    parts: list[str] = []
    if personas:
        labels = ", ".join(persona.split(":", 1)[-1] for persona in personas)
        if listed_all:
            parts.append(f"Available personas: {labels}.")
        else:
            parts.append(f"{labels}.")
    if paths:
        parts.append("Files: " + ", ".join(paths) + ".")
    if omitted:
        parts.append("Left out because of the size cap: " + ", ".join(omitted) + ".")
    if graph_notes:
        parts.append(" ".join(graph_notes))
    summary = " ".join(parts) or "Files and skills for this task."
    if items:
        verdict = "ok"
        directive = "proceed_and_cite"
    elif personas:
        verdict = "ok_with_notes"
        directive = "proceed"
    else:
        verdict = "no_knowledge"
        directive = "proceed"
    return _finish(
        project,
        persona="task",
        intent=intent,
        file_path=file_path,
        verdict=verdict,
        directive=directive,
        summary=summary,
        items=items,
        omitted=omitted,
        drafts=drafts,
        limit=limit,
        graph_notes=graph_notes,
        used=used,
        files=files,
        personas=personas,
    )


def _path_tokens(file_path: str, paths: list[str]) -> set[str]:
    bits: list[str] = []
    for raw in (file_path, *paths):
        if not raw:
            continue
        normalized = raw.replace("\\", "/")
        bits.append(normalized)
        bits.append(Path(normalized).stem)
        bits.append(Path(normalized).suffix.lstrip("."))
        bits.extend(Path(normalized).parts)
    return _tokens(" ".join(bits)) | {
        part.lower()
        for part in bits
        if part and len(part) >= 2 and part.replace(".", "").isalnum()
    }


def _personas_from_path_hints(
    stable: list[tuple[str, Doc]],
    path_words: set[str],
) -> list[str]:
    if not path_words:
        return []
    matched: list[str] = []
    for name, _doc in stable:
        slug = persona_slug(name)
        for hint, tokens in _PATH_HINTS.items():
            if hint not in slug:
                continue
            if path_words & tokens:
                matched.append(name)
                break
    return matched


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 4 and token not in _STOP
    }


def _expand(words: set[str]) -> set[str]:
    out = set(words)
    for word in words:
        out |= set(_ALIASES.get(word, ()))
    return out


def _query_tokens(text: str) -> set[str]:
    """Tokenize intent/path text and fold in short alias keys found as whole words."""
    base = _tokens(text)
    lower = text.lower()
    for key in _ALIASES:
        if re.search(rf"\b{re.escape(key)}\b", lower):
            base.add(key)
    return _expand(base)


def _overlap_score(hay: set[str], query: set[str]) -> int:
    return len(hay & query)


def _persona_tokens(doc: Doc, name: str) -> set[str]:
    bits = [
        persona_slug(name),
        str(doc.get("title") or ""),
        str(doc.get("summary") or ""),
        str(doc.get("description") or ""),
    ]
    body = (doc.body or "").strip()
    if body:
        bits.append(body.split("\n", 1)[0][:240])
    return _tokens(" ".join(bits))


def _skill_tokens(skill: Doc) -> set[str]:
    # Do not index the skill id — persona slug tokens there match every skill
    # under that role and drown out title/summary signal.
    bits = [
        str(skill.get("title") or ""),
        str(skill.get("summary") or ""),
        str(skill.get("description") or ""),
        str(skill.get("when_to_use") or ""),
    ]
    tags = skill.header.get("tags")
    if isinstance(tags, list):
        bits.extend(str(tag) for tag in tags)
    elif tags:
        bits.append(str(tags))
    return _tokens(" ".join(bits))


def _refresh_map(maps: Path, notes: list[str]) -> None:
    from lore.setup.graph_job import ensure_fresh

    note = ensure_fresh(maps)
    if note and note not in notes:
        notes.append(note)


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
    files: list[dict[str, Any]] | None = None,
    personas: list[str] | None = None,
) -> dict[str, Any]:
    included = [str(item["id"]) for item in items]
    cite_ids = [str(item["id"]) for item in items if item.get("kind") == "skill"]
    if cite_ids:
        summary = f"{summary} Cite: {', '.join(cite_ids)}."
    if used is None:
        used = count_tokens(summary)
    record = allocate(
        project,
        {
            "tool": "get_context",
            "verdict": verdict,
            "directive": directive,
            "persona": persona,
            "included": included,
            "omitted": omitted,
            "client": os.environ.get("LORE_CLIENT", "").strip() or "Unknown",
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
        "links": [
            f"lore://personas/{name.split(':', 1)[-1]}"
            for name in (personas if personas is not None else [persona])
            if name and name != "task"
        ]
        + [f"lore://skills/{str(item['id']).removeprefix('skill:')}" for item in items if item["kind"] == "skill"],
        "data": {
            "persona": persona,
            "omitted": omitted,
            "graph_notes": graph_notes,
            "cite_ids": cite_ids,
            **({"files": files} if files is not None else {}),
            **({"personas": personas} if personas is not None else {}),
        },
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

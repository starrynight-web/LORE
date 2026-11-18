"""Counts of how agents have called Lore, from the decision files."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TypedDict

from lore.core.config import load_config
from lore.core.decisions import list_decisions
from lore.core.personas import list_personas, list_skill_files


class Rank(TypedDict):
    id: str
    name: str
    count: int


class RecentCall(TypedDict):
    id: str
    time: str
    client: str
    persona: str
    verdict: str
    summary: str
    tokens_used: int | None
    token_budget: int | None


class TokenPoint(TypedDict):
    id: str
    time: str
    tokens_used: int
    token_budget: int
    persona: str
    client: str


class TokenStats(TypedDict):
    total: int
    avg: int
    max: int
    budget: int
    tracked_calls: int
    series: list[TokenPoint]


class Usage(TypedDict):
    calls: int
    agents: list[Rank]
    personas: list[Rank]
    skills: list[Rank]
    recent: list[RecentCall]
    tokens: TokenStats
    tokens_by_persona: dict[str, int]


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def summary(project: Path) -> Usage:
    decisions = list_decisions(project)
    config_budget = int(load_config(project / ".lore")["token_budget"])
    agents: Counter[str] = Counter()
    personas: Counter[str] = Counter()
    skills: Counter[str] = Counter()
    tokens_by_persona: Counter[str] = Counter()
    persona_names = _persona_names(project)
    skill_names = _skill_names(project)
    recent: list[RecentCall] = []
    series: list[TokenPoint] = []
    total_tokens = 0
    max_tokens = 0
    tracked_calls = 0

    for doc in decisions:
        client = str(doc.header.get("client") or "Unknown")
        agents[client] += 1
        persona = doc.get("persona")
        if persona:
            personas[persona] += 1
        included = doc.header.get("included")
        if isinstance(included, list):
            for item in included:
                ident = str(item)
                if ident.startswith("skill:"):
                    skills[ident] += 1
        used = _int_or_none(doc.header.get("tokens_used"))
        budget = _int_or_none(doc.header.get("token_budget"))
        persona_label = persona_names.get(persona, persona)
        if used is not None:
            tracked_calls += 1
            total_tokens += used
            max_tokens = max(max_tokens, used)
            if persona:
                tokens_by_persona[persona_label or persona] += used
            series.append(
                {
                    "id": doc.get("id"),
                    "time": doc.get("time"),
                    "tokens_used": used,
                    "token_budget": budget if budget is not None else config_budget,
                    "persona": persona_label,
                    "client": client,
                }
            )
        recent.append(
            {
                "id": doc.get("id"),
                "time": doc.get("time"),
                "client": client,
                "persona": persona_label,
                "verdict": doc.get("verdict"),
                "summary": doc.body.strip(),
                "tokens_used": used,
                "token_budget": budget,
            }
        )

    avg_tokens = round(total_tokens / tracked_calls) if tracked_calls else 0
    return {
        "calls": len(decisions),
        "agents": _ranked(agents, {name: name for name in agents}),
        "personas": _ranked(personas, persona_names),
        "skills": _ranked(skills, skill_names),
        "recent": list(reversed(recent[-8:])),
        "tokens": {
            "total": total_tokens,
            "avg": avg_tokens,
            "max": max_tokens,
            "budget": config_budget,
            "tracked_calls": tracked_calls,
            "series": series[-16:],
        },
        "tokens_by_persona": dict(tokens_by_persona.most_common()),
    }


def _ranked(counter: Counter[str], names: dict[str, str]) -> list[Rank]:
    rows: list[Rank] = []
    for ident, count in counter.most_common():
        rows.append({"id": ident, "name": names.get(ident, ident), "count": count})
    return rows


def _persona_names(project: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for doc in list_personas(project):
        names[doc.get("id")] = doc.get("title") or doc.get("id")
    return names


def _skill_names(project: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for _path, doc in list_skill_files(project):
        names[doc.get("id")] = doc.get("title") or doc.get("id")
    return names

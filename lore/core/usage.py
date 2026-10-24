"""Counts of how agents have called Lore, from the decision files."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TypedDict

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


class Usage(TypedDict):
    calls: int
    agents: list[Rank]
    personas: list[Rank]
    skills: list[Rank]
    recent: list[RecentCall]


def summary(project: Path) -> Usage:
    decisions = list_decisions(project)
    agents: Counter[str] = Counter()
    personas: Counter[str] = Counter()
    skills: Counter[str] = Counter()
    persona_names = _persona_names(project)
    skill_names = _skill_names(project)
    recent: list[RecentCall] = []
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
        recent.append(
            {
                "id": doc.get("id"),
                "time": doc.get("time"),
                "client": client,
                "persona": persona_names.get(persona, persona),
                "verdict": doc.get("verdict"),
                "summary": doc.body.strip(),
            }
        )
    return {
        "calls": len(decisions),
        "agents": _ranked(agents, {name: name for name in agents}),
        "personas": _ranked(personas, persona_names),
        "skills": _ranked(skills, skill_names),
        "recent": list(reversed(recent[-8:])),
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

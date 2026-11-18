"""CLI: lore-solo stats [--json]."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lore.core.paths import LoreNotFound, find_project
from lore.core.usage import summary as usage_summary


def _project() -> Path:
    try:
        return find_project(Path.cwd())
    except LoreNotFound as exc:
        raise SystemExit("No .lore folder found. Run lore-solo setup first.") from exc


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lore-solo stats", description="Show call and token telemetry.")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args(argv)

    data = usage_summary(_project())
    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    tokens = data["tokens"]
    print(f"Calls: {data['calls']} (tracked: {tokens['tracked_calls']})")
    print(
        f"Tokens: total={tokens['total']} avg={tokens['avg']} "
        f"max={tokens['max']} budget={tokens['budget']}"
    )
    if data["agents"]:
        top_agents = ", ".join(f"{r['name']} ({r['count']})" for r in data["agents"][:5])
        print(f"Agents: {top_agents}")
    if data["personas"]:
        top_personas = ", ".join(f"{r['name']} ({r['count']})" for r in data["personas"][:5])
        print(f"Personas: {top_personas}")
    if data["skills"]:
        top_skills = ", ".join(f"{r['name']} ({r['count']})" for r in data["skills"][:5])
        print(f"Skills: {top_skills}")
    return 0

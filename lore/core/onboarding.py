"""Whether a new library still needs the setup steps."""

from __future__ import annotations

import json
from pathlib import Path

from lore.core.personas import list_personas, list_skill_files

STEPS = ("welcome", "skills", "persona", "codebase", "done")


def _file(project: Path) -> Path:
    return project / ".lore" / "onboarding.json"


def _read(path: Path) -> dict[str, bool | str]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        loaded = {}
    if not isinstance(loaded, dict):
        loaded = {}
    step = str(loaded.get("step", "welcome"))
    if step not in STEPS:
        step = "welcome"
    completed = bool(loaded.get("completed"))
    if completed:
        step = "done"
    return {"completed": completed, "step": step}


def state(project: Path) -> dict[str, bool | str]:
    """New empty libraries start at the greeting. A library that already has files does not."""
    path = _file(project)
    if path.is_file():
        return _read(path)
    if list_personas(project) or list_skill_files(project):
        return {"completed": True, "step": "done"}
    return {"completed": False, "step": "welcome"}


def save(project: Path, *, completed: bool, step: str) -> dict[str, bool | str]:
    if step not in STEPS:
        raise ValueError("Unknown setup step.")
    chosen = "done" if completed else step
    payload: dict[str, bool | str] = {"completed": completed, "step": chosen}
    path = _file(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return payload

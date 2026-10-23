"""Remember the first result for an idempotency key."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _path(project: Path) -> Path:
    return project / ".lore" / "idempotency.json"


def recall(project: Path, key: str) -> dict[str, Any] | None:
    path = _path(project)
    if not key or not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    found = data.get(key)
    if isinstance(found, dict):
        return found
    return None


def remember(project: Path, key: str, payload: dict[str, Any]) -> None:
    if not key:
        return
    path = _path(project)
    data: dict[str, Any] = {}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    data[key] = payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

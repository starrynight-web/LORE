"""Codebases the person has asked Lore to map."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lore.core.personas import file_slug


def _file(project: Path) -> Path:
    return project / ".lore" / "codebases.json"


def list_codebases(project: Path) -> list[dict[str, str]]:
    path = _file(project)
    if not path.is_file():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    rows: list[dict[str, str]] = []
    for item in loaded:
        if not isinstance(item, dict):
            continue
        ident = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        folder = str(item.get("path", "")).strip()
        if ident and name and folder:
            rows.append({"id": ident, "name": name, "path": folder})
    return rows


def get_codebase(project: Path, ident: str) -> dict[str, str]:
    for row in list_codebases(project):
        if row["id"] == ident:
            return row
    raise FileNotFoundError(ident)


def add_codebase(project: Path, name: str, folder: Path) -> dict[str, str]:
    title = name.strip()
    if not title:
        raise ValueError("A codebase needs a name.")
    if not folder.is_dir():
        raise ValueError("That path is not a folder.")
    rows = list_codebases(project)
    slug = file_slug(title)
    taken = {row["id"] for row in rows}
    ident = slug
    number = 2
    while ident in taken:
        ident = f"{slug}-{number}"
        number += 1
    row = {"id": ident, "name": title, "path": str(folder.resolve())}
    rows.append(row)
    _write(project, rows)
    return row


def rename_codebase(project: Path, ident: str, name: str) -> dict[str, str]:
    title = name.strip()
    if not title:
        raise ValueError("A codebase needs a name.")
    rows = list_codebases(project)
    for row in rows:
        if row["id"] == ident:
            row["name"] = title
            _write(project, rows)
            return row
    raise FileNotFoundError(ident)


def delete_codebase(project: Path, ident: str) -> dict[str, str]:
    rows = list_codebases(project)
    kept = [row for row in rows if row["id"] != ident]
    if len(kept) == len(rows):
        raise FileNotFoundError(ident)
    removed = next(row for row in rows if row["id"] == ident)
    _write(project, kept)
    return removed


def remove_map(folder: Path) -> None:
    """Delete the map files Lore wrote. Source files stay."""
    graph = folder / "graphify-out"
    if graph.is_dir():
        shutil.rmtree(graph)
    status = folder / ".lore" / "graph-status.json"
    if status.is_file():
        status.unlink()


def _write(project: Path, rows: list[dict[str, str]]) -> None:
    path = _file(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

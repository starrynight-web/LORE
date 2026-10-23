"""Decision files under `.lore/decisions/`."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lore.core.okf import Doc, read_doc, write_doc


def decisions_dir(project: Path) -> Path:
    folder = project / ".lore" / "decisions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def allocate(project: Path, header: dict[str, Any], body: str) -> Doc:
    folder = decisions_dir(project)
    number = 1
    while True:
        ident = f"dec-{number:04d}"
        path = folder / f"{ident}.md"
        try:
            path.open("x", encoding="utf-8").close()
        except FileExistsError:
            number += 1
            continue
        header = {"id": ident, **header, "time": _now()}
        doc = Doc(header=header, body=body, path=path)
        write_doc(path, doc)
        return doc


def read_decision(project: Path, decision_id: str) -> Doc:
    path = project / ".lore" / "decisions" / f"{decision_id}.md"
    if not path.is_file():
        raise FileNotFoundError(decision_id)
    return read_doc(path)


def append_outcome(project: Path, decision_id: str, outcome: str, note: str = "") -> Doc:
    doc = read_decision(project, decision_id)
    extra = outcome if not note else f"{outcome}\n{note}"
    doc.body = doc.body.rstrip() + "\n\n" + extra + "\n"
    if doc.path is None:
        raise FileNotFoundError(decision_id)
    write_doc(doc.path, doc)
    return doc


def list_decisions(project: Path) -> list[Doc]:
    folder = project / ".lore" / "decisions"
    if not folder.is_dir():
        return []
    return [read_doc(path) for path in sorted(folder.glob("dec-*.md"))]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()

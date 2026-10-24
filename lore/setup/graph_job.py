"""Run Graphify from Lore's own environment. The agent never calls this."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lore.core.graph import KNOWN_SCHEMA, _version


def _graphify() -> Path:
    names = ("graphify.exe", "graphify") if os.name == "nt" else ("graphify",)
    for name in names:
        beside = Path(sys.executable).with_name(name)
        if beside.is_file():
            return beside
    found = shutil.which("graphify")
    if found is not None:
        return Path(found)
    raise RuntimeError("Graphify is not installed in this Lore environment.")


def run_graphify(project: Path) -> None:
    exe = _graphify()
    extract = subprocess.run(
        [str(exe), "extract", str(project), "--code-only", "--out", str(project)],
        capture_output=True,
        text=True,
        check=False,
    )
    if extract.returncode != 0:
        detail = (extract.stderr or extract.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "The codebase map could not be built."
        raise RuntimeError(message)
    graph = project / "graphify-out" / "graph.json"
    if not graph.is_file():
        raise RuntimeError("The map finished without a graph file.")
    html = project / "graphify-out" / "graph.html"
    if not html.is_file():
        subprocess.run(
            [str(exe), "export", "html", "--graph", str(graph)],
            capture_output=True,
            text=True,
            check=False,
        )


def start_build(project: Path, status_path: Path | None = None) -> dict[str, Any]:
    status_path = status_path or (project / ".lore" / "graph-status.json")
    current = _read(status_path)
    if current.get("state") == "running":
        return current
    _write(status_path, {"state": "running"})
    threading.Thread(target=_job, args=(project, status_path), daemon=True).start()
    return {"state": "running"}


def _job(project: Path, status_path: Path) -> None:
    try:
        run_graphify(project)
        data = json.loads((project / "graphify-out" / "graph.json").read_text(encoding="utf-8"))
        version = _version(data) if isinstance(data, dict) else None
        if version not in KNOWN_SCHEMA:
            raise RuntimeError("The map used a format Lore does not read yet.")
        _write(
            status_path,
            {
                "state": "ready",
                "time": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "schema_version": version,
            },
        )
    except Exception as exc:  # noqa: BLE001 - any map failure must settle the status file
        _write(status_path, {"state": "failed", "error": str(exc) or "The codebase map failed."})


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

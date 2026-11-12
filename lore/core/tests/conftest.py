from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_workspace_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer shell may set LORE_WORKSPACE. Tests choose the folder themselves."""
    monkeypatch.delenv("LORE_WORKSPACE", raising=False)

import sys
import time
from pathlib import Path
from typing import Any

from lore.setup.graph_job import start_build as _real_start_build


@pytest.fixture(autouse=True)
def map_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never spawn map workers unless they opt in explicitly."""
    monkeypatch.setenv("LORE_MAP_ENABLED", "0")


@pytest.fixture()
def enable_map(monkeypatch: pytest.MonkeyPatch, fake_graphify: Path) -> list[dict[str, Any]]:
    """Mapping enabled with a stubbed scheduler; returns recorded start_build calls.

    The fake Graphify executable is provisioned too: map_capability probes the
    LORE_GRAPHIFY binary and CI dev envs have no real graphifyy installed.
    """
    monkeypatch.setenv("LORE_MAP_ENABLED", "1")
    calls: list[dict[str, Any]] = []

    def fake_start_build(
        project: Path, status_path: Path | None = None, *, force: bool = False
    ) -> dict[str, Any]:
        from lore.core.graph import write_status

        calls.append({"project": Path(project), "force": force})
        status = {
            "state": "running",
            "job_id": "stub-job",
            "started_ts": time.time(),
        }
        write_status(Path(project), status)
        return dict(status)

    monkeypatch.setattr("lore.setup.graph_job.start_build", fake_start_build)
    return calls


_FAKE_GRAPHIFY = """#!{python}
import json
import os
import shutil
import sys
import time
from pathlib import Path

SKIP = {".git", ".lore", ".venv", "node_modules", "graphify-out", "__pycache__"}


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--version":
        print("graphify 0.0.0-test")
        return 0
    if args and args[0] == "export":
        return 0
    if not args or args[0] != "extract":
        return 2
    source = Path(args[1])
    out = Path(args[args.index("--out") + 1])
    delay = float(os.environ.get("LORE_FAKE_GRAPHIFY_SLEEP", "0") or 0)
    if delay:
        time.sleep(delay)
    if os.environ.get("LORE_FAKE_GRAPHIFY_FAIL"):
        print("fake extract failed", file=sys.stderr)
        return 3
    target = out / "graphify-out"
    target.mkdir(parents=True, exist_ok=True)
    fixture = os.environ.get("LORE_FAKE_GRAPHIFY_GRAPH", "").strip()
    if fixture:
        shutil.copyfile(fixture, target / "graph.json")
    else:
        nodes = []
        for path in sorted(source.rglob("*")):
            if not path.is_file() or any(part in SKIP for part in path.parts):
                continue
            rel = path.relative_to(source).as_posix()
            nodes.append(
                {
                    "id": rel.replace("/", "_").replace(".", "_"),
                    "label": path.name,
                    "source_file": rel,
                }
            )
        graph = {
            "graph": {"schema_version": 1, "graphify_version": "0.0.0-test"},
            "nodes": nodes,
            "links": [],
            "hyperedges": [],
            "built_at_commit": "0" * 40,
        }
        (target / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    (target / "graph.html").write_text("<p>map</p>", encoding="utf-8")
    marker = os.environ.get("LORE_FAKE_GRAPHIFY_MARKER", "").strip()
    if marker:
        with open(marker, "a", encoding="utf-8") as handle:
            handle.write("extract\\n")
    return 0


sys.exit(main())
"""


@pytest.fixture()
def fake_graphify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fast stand-in Graphify executable; worker subprocesses run it for real."""
    from lore.core.graph_fingerprint import _graphify_version

    exe = tmp_path / "graphify.py"
    exe.write_text(_FAKE_GRAPHIFY.replace("{python}", sys.executable), encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("LORE_GRAPHIFY", str(exe))
    _graphify_version.cache_clear()
    return exe


@pytest.fixture()
def real_build(
    enable_map: list[dict[str, Any]],
    fake_graphify: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Restore the real start_build so tests exercise actual worker subprocesses."""
    monkeypatch.setattr("lore.setup.graph_job.start_build", _real_start_build)
    return fake_graphify

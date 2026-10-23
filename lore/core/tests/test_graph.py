from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from lore.core.context import get_context
from lore.core.decisions import read_decision
from lore.core.tests.pack import PACK
from lore.core.workspace import init_workspace


def _project(tmp_path: Path) -> Path:
    dest = tmp_path / "app"
    shutil.copytree(PACK, dest)
    return dest


def test_file_neighborhood_stays_inside_the_cap(tmp_path: Path) -> None:
    project = _project(tmp_path)
    envelope = get_context(project, "frontend-engineer", file_path="src/ui/Button.tsx")
    paths = [item["source"]["path"] for item in envelope["items"]]
    assert "src/ui/Button.tsx" in paths
    assert "src/ui/theme.ts" in paths
    assert len(envelope["items"]) <= 8
    assert envelope["budget"]["used"] <= 800
    saved = read_decision(project, envelope["decision_id"])
    included = saved.header["included"]
    assert any(str(item).startswith("chunk:") for item in included)


def test_missing_map_still_returns_skills(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "graphify-out" / "graph.json").unlink()
    envelope = get_context(project, "frontend-engineer")
    assert [item["id"] for item in envelope["items"]] == [
        "skill:frontend-engineer/react-practices@v1",
        "skill:frontend-engineer/tailwind-rules@v1",
        "skill:frontend-engineer/ui-ux-pro-max@v1",
    ]
    assert "Map this project" in envelope["summary"]


def test_unknown_schema_asks_for_a_map(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = project / "graphify-out" / "graph.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["graph"]["schema_version"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    envelope = get_context(project, "frontend-engineer")
    assert all(item["kind"] == "skill" for item in envelope["items"])
    assert "Map this project" in envelope["summary"]


def test_build_status_moves_to_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = init_workspace(tmp_path / "app")
    fixture = PACK / "graphify-out" / "graph.json"

    def fake(target: Path) -> None:
        out = target / "graphify-out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "graph.json").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
        (out / "graph.html").write_text("<p>map</p>", encoding="utf-8")

    monkeypatch.setattr("lore.setup.graph_job.run_graphify", fake)
    from lore.setup.graph_job import start_build

    assert start_build(project)["state"] == "running"
    status: dict[str, Any] = {}
    for _ in range(50):
        status = json.loads((project / ".lore" / "graph-status.json").read_text(encoding="utf-8"))
        if status.get("state") != "running":
            break
        time.sleep(0.05)
    assert status["state"] == "ready"
    assert status["schema_version"] == 1

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from lore.core.context import get_context
from lore.core.decisions import read_decision
from lore.core.graph import locate
from lore.core.paths import find_project, map_root
from lore.core.personas import write_persona, write_skill
from lore.core.tests.pack import PACK
from lore.core.tests.test_mcp import _payload
from lore.core.workspace import init_workspace
from lore.mcp_server import build


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


def test_missing_map_still_returns_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    (project / "graphify-out" / "graph.json").unlink()

    def skip_live(_target: Path) -> None:
        raise RuntimeError("skip live extract")

    monkeypatch.setattr("lore.setup.graph_job.run_graphify", skip_live)
    envelope = get_context(project, "frontend-engineer")
    assert [item["id"] for item in envelope["items"]] == [
        "skill:frontend-engineer/react-practices@v1",
        "skill:frontend-engineer/tailwind-rules@v1",
        "skill:frontend-engineer/ui-ux-pro-max@v1",
    ]
    assert "Map this project" in envelope["summary"]
    assert "The map is building." in envelope["summary"]
    _wait_until_settled(project)


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


def test_server_instructions_tell_the_agent_to_call_lore(tmp_path: Path) -> None:
    server = build(tmp_path)
    text = getattr(server, "instructions", None)
    assert isinstance(text, str)
    assert "get_context once" in text
    assert "map_codebase" in text


def test_locate_ui_change_stays_on_the_ui_files(tmp_path: Path) -> None:
    project = _project(tmp_path)
    found = locate(project, "UI change")
    paths = [item["path"] for item in found["files"]]
    assert "src/ui/Button.tsx" in paths
    assert "src/ui/theme.ts" in paths
    assert all("mcp.json" not in path for path in paths)
    assert len(paths) <= 8
    assert found["budget"]["used"] <= found["budget"]["limit"]


def test_running_build_does_not_start_a_second_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    (project / ".lore" / "graph-status.json").write_text(
        json.dumps({"state": "running"}) + "\n",
        encoding="utf-8",
    )
    calls: list[Path] = []
    monkeypatch.setattr("lore.setup.graph_job.run_graphify", lambda target: calls.append(target))
    first = get_context(project, "frontend-engineer", file_path="src/ui/Button.tsx")
    second = get_context(project, "frontend-engineer", file_path="src/ui/Button.tsx")
    assert calls == []
    assert "The map is building." in first["summary"]
    assert "The map is building." in second["summary"]
    assert any(item["source"]["path"] == "src/ui/Button.tsx" for item in first["items"])


def test_stale_commit_serves_the_old_map_while_rebuilding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    graph_path = project / "graphify-out" / "graph.json"
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    data["built_at_commit"] = "0" * 40
    graph_path.write_text(json.dumps(data), encoding="utf-8")
    _commit(project)
    started = {"count": 0}
    release = threading.Event()

    def hold(_target: Path) -> None:
        started["count"] += 1
        release.wait(3)

    monkeypatch.setattr("lore.setup.graph_job.run_graphify", hold)
    try:
        first = get_context(project, "frontend-engineer", file_path="src/ui/Button.tsx")
        for _ in range(50):
            if started["count"] == 1:
                break
            time.sleep(0.05)
        second = get_context(project, "frontend-engineer", file_path="src/ui/Button.tsx")
        assert started["count"] == 1
        assert "The map is building." in first["summary"]
        assert "The map is building." in second["summary"]
        assert any(item["source"]["path"] == "src/ui/Button.tsx" for item in second["items"])
    finally:
        release.set()
        _wait_until_settled(project)


def test_repo_without_lore_maps_itself_and_reads_the_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "library"
    init_workspace(library)
    write_persona(
        library,
        "Frontend engineer",
        "UI work.",
        "Use the UI skills.\n",
        status="stable",
    )
    write_skill(
        library,
        "frontend-engineer",
        "react-practices",
        title="React",
        summary="Prefer function components.",
        body="Use functions.\n",
        status="stable",
    )
    repo = tmp_path / "repo"
    (repo / "src" / "ui").mkdir(parents=True)
    (repo / "src" / "ui" / "Button.tsx").write_text("export const Button = () => null\n", encoding="utf-8")
    monkeypatch.setenv("LORE_LIBRARY", str(library))
    assert find_project(repo) == library.resolve()
    assert map_root(repo) == repo.resolve()
    fixture = (PACK / "graphify-out" / "graph.json").read_text(encoding="utf-8")

    def fake(target: Path) -> None:
        out = target / "graphify-out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "graph.json").write_text(fixture, encoding="utf-8")

    monkeypatch.setattr("lore.setup.graph_job.run_graphify", fake)

    async def call() -> None:
        async with Client(build(repo)) as client:
            started = _payload(await client.call_tool("map_codebase", {}))
            assert isinstance(started, dict)
            assert started["state"] == "running"

    asyncio.run(call())
    _wait_until_settled(repo)
    located = locate(repo, "UI change")
    paths = [item["path"] for item in located["files"]]
    assert "src/ui/Button.tsx" in paths
    assert "src/ui/theme.ts" in paths
    assert (repo / "graphify-out" / "graph.json").is_file()
    assert not (library / "graphify-out").exists()
    envelope = get_context(repo, "frontend-engineer", file_path="src/ui/Button.tsx")
    assert any(item["id"] == "skill:frontend-engineer/react-practices@v1" for item in envelope["items"])
    assert any(item["source"]["path"] == "src/ui/Button.tsx" for item in envelope["items"])
    assert find_project(repo) == library.resolve()


def _wait_until_settled(project: Path) -> None:
    status_path = project / ".lore" / "graph-status.json"
    for _ in range(50):
        if status_path.is_file():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("state") != "running":
                return
        time.sleep(0.05)


def _commit(project: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Lore",
            "GIT_AUTHOR_EMAIL": "lore@example.com",
            "GIT_COMMITTER_NAME": "Lore",
            "GIT_COMMITTER_EMAIL": "lore@example.com",
        }
    )
    subprocess.run(["git", "init"], cwd=project, check=True, env=env, capture_output=True)
    subprocess.run(["git", "add", "graphify-out/graph.json"], cwd=project, check=True, env=env, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "map"],
        cwd=project,
        check=True,
        env=env,
        capture_output=True,
    )

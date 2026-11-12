from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from lore.core.context import get_context
from lore.core.decisions import read_decision
from lore.core.graph import locate, lock_file, map_status, read_status
from lore.core.map_lock import MapLock
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


def test_missing_map_still_returns_skills(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    project = _project(tmp_path)
    (project / "graphify-out" / "graph.json").unlink()
    envelope = get_context(project, "frontend-engineer")
    assert [item["id"] for item in envelope["items"]] == [
        "skill:frontend-engineer/react-practices@v1",
        "skill:frontend-engineer/tailwind-rules@v1",
        "skill:frontend-engineer/ui-ux-pro-max@v1",
    ]
    assert "Map this project" in envelope["summary"]
    assert "The map is building." in envelope["summary"]
    assert len(enable_map) == 1


def test_unknown_schema_asks_for_a_map(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = project / "graphify-out" / "graph.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["graph"]["schema_version"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    envelope = get_context(project, "frontend-engineer")
    assert all(item["kind"] == "skill" for item in envelope["items"])
    assert "Map this project" in envelope["summary"]


def test_build_status_moves_to_ready(tmp_path: Path, real_build: Path) -> None:
    project = init_workspace(tmp_path / "app")
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    from lore.setup.graph_job import start_build

    started = start_build(project)
    assert started["state"] in {"running", "ready"}
    status = _wait_until_settled(project)
    assert status["state"] == "ready"
    assert status["schema_version"] == 1
    assert status["job_id"] == started["job_id"]
    assert status["stale"] is False


def test_server_instructions_tell_the_agent_to_call_lore(tmp_path: Path) -> None:
    server = build(tmp_path)
    text = getattr(server, "instructions", None)
    assert isinstance(text, str)
    assert "get_context once" in text
    assert "map_codebase" in text
    assert "check_applied" in text
    assert "log_decision" in text
    assert "get_skill" in text
    assert "advisory" in text
    assert "Edit only those files" not in text


def test_locate_ui_change_stays_on_the_ui_files(tmp_path: Path) -> None:
    project = _project(tmp_path)
    found = locate(project, "UI change")
    paths = [item["path"] for item in found["files"]]
    assert "src/ui/Button.tsx" in paths
    assert "src/ui/theme.ts" in paths
    assert all("mcp.json" not in path for path in paths)
    assert len(paths) <= 8
    assert found["budget"]["used"] <= found["budget"]["limit"]


def test_locate_never_returns_paths_outside_the_project(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = project / "graphify-out" / "graph.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["nodes"].append(
        {
            "id": "escape_evil",
            "label": "evil.py",
            "source_file": "../evil.py",
        }
    )
    data["nodes"].append(
        {
            "id": "escape_abs",
            "label": "evil-abs.py",
            "source_file": "/etc/evil.py",
        }
    )
    path.write_text(json.dumps(data), encoding="utf-8")
    found = locate(project, "evil")
    assert found["files"] == []
    assert all(".." not in item["path"] for item in found["files"])
    neighborhood = get_context(project, "frontend-engineer", file_path="../evil.py")
    assert all(
        item["source"]["path"] != "../evil.py"
        for item in neighborhood["items"]
        if item["kind"] == "chunk"
    )


def test_running_build_does_not_start_a_second_process(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    project = _project(tmp_path)
    (project / ".lore" / "graph-status.json").write_text(
        json.dumps({"state": "running", "started_ts": time.time() - 3600}) + "\n",
        encoding="utf-8",
    )
    lock = MapLock(lock_file(project))
    assert lock.acquire()
    try:
        first = get_context(project, "frontend-engineer", file_path="src/ui/Button.tsx")
        second = get_context(project, "frontend-engineer", file_path="src/ui/Button.tsx")
        assert enable_map == []
        assert "The map is building." in first["summary"]
        assert "The map is building." in second["summary"]
        assert any(item["source"]["path"] == "src/ui/Button.tsx" for item in first["items"])
    finally:
        lock.release()


def test_unlocked_running_status_reads_as_interrupted(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / ".lore" / "graph-status.json").write_text(
        json.dumps({"state": "running", "started_ts": time.time() - 3600}) + "\n",
        encoding="utf-8",
    )
    status = read_status(project)
    assert status["state"] == "interrupted"
    assert status["error_code"] == "worker_exit"
    persisted = json.loads((project / ".lore" / "graph-status.json").read_text(encoding="utf-8"))
    assert persisted["state"] == "running"


def test_status_read_survives_a_torn_write(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = project / ".lore" / "graph-status.json"
    path.write_text('{"state": "run', encoding="utf-8")
    status = read_status(project)
    assert status["state"] == "failed"
    assert status["error_code"] == "status_read"


def test_map_opt_out_never_probes_or_spawns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    monkeypatch.setenv("LORE_MAP_ENABLED", "0")

    def probe() -> Path:
        raise AssertionError("graphify must not be probed while disabled")

    def spawn(project_arg: Path, job_id: str) -> None:
        raise AssertionError("worker must not spawn while disabled")

    monkeypatch.setattr("lore.setup.graph_job._graphify", probe)
    monkeypatch.setattr("lore.setup.graph_job._spawn_worker", spawn)
    from lore.setup.graph_job import map_capability, start_build

    capability = map_capability()
    assert capability == {"available": False, "reason": "disabled"}
    status = map_status(project)
    assert status["available"] is False
    assert status["state"] == "unavailable"
    assert status["reason"] == "disabled"
    built = start_build(project, force=True)
    assert built["state"] == "unavailable"
    assert built["reason"] == "disabled"
    envelope = get_context(project, "frontend-engineer", file_path="src/ui/Button.tsx")
    assert [item["id"] for item in envelope["items"]][:1] == [
        "skill:frontend-engineer/react-practices@v1"
    ]
    assert envelope["data"]["map"]["available"] is False
    assert envelope["data"]["map"]["state"] == "unavailable"

    async def call() -> dict[str, Any]:
        async with Client(build(project)) as client:
            parsed = _payload(await client.call_tool("map_codebase", {}))
            assert isinstance(parsed, dict)
            return parsed

    result = asyncio.run(call())
    assert result["state"] == "unavailable"
    assert result["reason"] == "disabled"


def test_stale_map_coalesces_then_rebuilds(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    from lore.setup.graph_job import CEILING_SECONDS, QUIET_SECONDS, ensure_fresh

    project = _project(tmp_path)
    clock = {"now": 1_000.0}
    assert ensure_fresh(project, now=lambda: clock["now"]) == "The map will refresh shortly."
    assert enable_map == []
    clock["now"] += QUIET_SECONDS
    assert ensure_fresh(project, now=lambda: clock["now"]) == "The map is building."
    assert len(enable_map) == 1
    second = get_context(project, "frontend-engineer", file_path="src/ui/Button.tsx")
    assert "The map is building." in second["summary"]
    assert any(item["source"]["path"] == "src/ui/Button.tsx" for item in second["items"])
    assert CEILING_SECONDS > QUIET_SECONDS


def test_empty_tree_skips_map_rebuild(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    from lore.setup.graph_job import ensure_fresh

    project = init_workspace(tmp_path / "empty")
    assert ensure_fresh(project) is None
    assert enable_map == []


def test_stale_map_forces_rebuild_at_ceiling(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    from lore.setup.graph_job import CEILING_SECONDS, ensure_fresh

    project = _project(tmp_path)
    clock = {"now": 500.0}
    assert ensure_fresh(project, now=lambda: clock["now"]) == "The map will refresh shortly."
    clock["now"] += 10
    assert ensure_fresh(project, now=lambda: clock["now"]) == "The map will refresh shortly."
    clock["now"] += CEILING_SECONDS
    assert ensure_fresh(project, now=lambda: clock["now"]) == "The map is building."
    assert len(enable_map) == 1


def test_failed_build_is_not_retried_until_sources_change(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    from lore.core.graph import write_status
    from lore.core.graph_fingerprint import source_fingerprint
    from lore.setup.graph_job import ensure_fresh

    project = _project(tmp_path)
    write_status(
        project,
        {
            "state": "failed",
            "error": "The codebase map failed.",
            "source_fingerprint": source_fingerprint(project),
        },
    )
    note = ensure_fresh(project)
    assert note == "The codebase map failed."
    assert enable_map == []
    (project / "src" / "ui" / "New.tsx").write_text("export const N = 1\n", encoding="utf-8")
    clock = {"now": 2_000.0}
    assert ensure_fresh(project, now=lambda: clock["now"]) == "The map will refresh shortly."


def test_repo_without_lore_maps_itself_and_reads_the_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_build: Path
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
    (repo / "src" / "ui" / "theme.ts").write_text("export const theme = {}\n", encoding="utf-8")
    monkeypatch.setenv("LORE_LIBRARY", str(library))
    monkeypatch.setenv(
        "LORE_FAKE_GRAPHIFY_GRAPH", str(PACK / "graphify-out" / "graph.json")
    )
    assert find_project(repo) == library.resolve()
    assert map_root(repo) == repo.resolve()

    async def call() -> None:
        async with Client(build(repo)) as client:
            started = _payload(await client.call_tool("map_codebase", {}))
            assert isinstance(started, dict)
            assert started["state"] in {"running", "ready"}

    asyncio.run(call())
    status = _wait_until_settled(repo)
    assert status["state"] == "ready"
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


def _wait_until_settled(project: Path) -> dict[str, Any]:
    status_path = project / ".lore" / "graph-status.json"
    status: dict[str, Any] = {}
    for _ in range(200):
        if status_path.is_file():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                time.sleep(0.05)
                continue
            if status.get("state") != "running":
                return status
        time.sleep(0.05)
    raise AssertionError(f"map build never settled: {status}")


def test_graph_paths_reject_windows_and_unc_escapes(tmp_path: Path) -> None:
    from lore.core.graph import _contained

    project = tmp_path / "app"
    (project / "src").mkdir(parents=True)
    assert _contained(project, "src/app.py")
    assert _contained(project, "./src/app.py")
    assert not _contained(project, "/etc/passwd")
    assert not _contained(project, "../outside.py")
    assert not _contained(project, "C:/windows/evil.py")
    assert not _contained(project, "C:\\windows\\evil.py")
    assert not _contained(project, "//server/share/evil.py")
    assert not _contained(project, "\\\\server\\share\\evil.py")


def test_canonical_status_wins_over_a_conflicting_legacy_mirror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_graphify: Path
) -> None:
    """UI (`summarize`) and MCP (`map_status`) share one canonical status."""
    from lore.core.graph import status_file, summarize, write_status

    monkeypatch.setenv("LORE_MAP_ENABLED", "1")
    project = tmp_path / "app"
    project.mkdir()
    legacy = tmp_path / "library" / ".lore" / "maps" / "app.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"state": "failed", "error": "stale mirror"}), encoding="utf-8"
    )
    write_status(project, {"state": "ready", "job_id": "job-1", "finished_at": "now"})
    assert summarize(project, legacy=legacy)["state"] == "ready"
    assert map_status(project, legacy=legacy)["state"] == "ready"
    status_file(project).unlink()
    assert summarize(project, legacy=legacy)["state"] == "failed"

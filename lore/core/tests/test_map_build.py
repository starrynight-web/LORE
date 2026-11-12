from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from lore import map_worker
from lore.core.graph import graph_file, lock_file, map_is_stale, read_status
from lore.core.graph_fingerprint import source_fingerprint
from lore.core.map_lock import MapLock
from lore.core.tests.pack import PACK
from lore.core.workspace import init_workspace


def _project(tmp_path: Path) -> Path:
    dest = tmp_path / "app"
    shutil.copytree(PACK, dest)
    return dest


def _fixture_extractor(target_graph: Path) -> Any:
    def extract(source: Path, out: Path) -> None:
        target = out / "graphify-out"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(target_graph, target / "graph.json")
        (target / "graph.html").write_text("<p>map</p>", encoding="utf-8")

    return extract


def _wait_for(predicate: Any, attempts: int = 200) -> None:
    for _ in range(attempts):
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("timed out waiting")


def test_worker_publishes_a_valid_graph(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    project = init_workspace(tmp_path / "app")
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    status = map_worker.run(
        project, "job-1", extract=_fixture_extractor(PACK / "graphify-out" / "graph.json")
    )
    assert status["state"] == "ready"
    assert status["job_id"] == "job-1"
    assert status["stale"] is False
    assert graph_file(project).is_file()
    assert (project / "graphify-out" / "graph.html").is_file()
    assert map_is_stale(project) is False


def test_worker_failure_preserves_the_last_good_graph(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    project = _project(tmp_path)
    before = graph_file(project).read_text(encoding="utf-8")

    def broken(source: Path, out: Path) -> None:
        raise RuntimeError("extract exploded")

    status = map_worker.run(project, "job-2", extract=broken)
    assert status["state"] == "failed"
    assert status["error_code"] == "extract_failed"
    assert "extract exploded" in status["error"]
    assert graph_file(project).read_text(encoding="utf-8") == before


def test_worker_rejects_an_unknown_or_escaping_graph(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    project = _project(tmp_path)
    before = graph_file(project).read_text(encoding="utf-8")
    escaping = json.loads(before)
    escaping["nodes"].append(
        {"id": "bad", "label": "bad.py", "source_file": "../../etc/passwd"}
    )

    def nasty(source: Path, out: Path) -> None:
        target = out / "graphify-out"
        target.mkdir(parents=True, exist_ok=True)
        (target / "graph.json").write_text(json.dumps(escaping), encoding="utf-8")

    status = map_worker.run(project, "job-3", extract=nasty)
    assert status["state"] == "failed"
    assert status["error_code"] == "invalid_graph"
    assert graph_file(project).read_text(encoding="utf-8") == before

    def unknown_schema(source: Path, out: Path) -> None:
        target = out / "graphify-out"
        target.mkdir(parents=True, exist_ok=True)
        data = json.loads(before)
        data["graph"]["schema_version"] = 99
        (target / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    status = map_worker.run(project, "job-4", extract=unknown_schema)
    assert status["state"] == "failed"
    assert status["error_code"] == "invalid_graph"
    assert graph_file(project).read_text(encoding="utf-8") == before


def test_worker_skips_when_another_build_holds_the_lock(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    project = _project(tmp_path)
    before = graph_file(project).read_text(encoding="utf-8")
    lock = MapLock(lock_file(project))
    assert lock.acquire()
    try:
        called: list[str] = []

        def extract(source: Path, out: Path) -> None:
            called.append("extract")

        status = map_worker.run(project, "job-5", extract=extract)
        assert status["state"] == "skipped"
        assert called == []
        assert graph_file(project).read_text(encoding="utf-8") == before
    finally:
        lock.release()


def test_source_changes_during_the_build_stay_stale(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    project = init_workspace(tmp_path / "app")
    (project / "src").mkdir()
    target = project / "src" / "app.py"
    target.write_text("print('hi')\n", encoding="utf-8")

    def mutating(source: Path, out: Path) -> None:
        target.write_text("print('changed during build')\n", encoding="utf-8")
        _fixture_extractor(PACK / "graphify-out" / "graph.json")(source, out)

    status = map_worker.run(project, "job-6", extract=mutating)
    assert status["state"] == "ready"
    assert status["stale"] is True


def test_fingerprint_tracks_dirty_untracked_and_deleted_files(tmp_path: Path) -> None:
    project = init_workspace(tmp_path / "app")
    src = project / "src"
    src.mkdir()
    tracked = src / "app.py"
    tracked.write_text("print('one')\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    base = source_fingerprint(project, force=True)
    tracked.write_text("print('two')\n", encoding="utf-8")
    assert source_fingerprint(project, force=True) != base
    base = source_fingerprint(project, force=True)
    (src / "new.py").write_text("print('new')\n", encoding="utf-8")
    assert source_fingerprint(project, force=True) != base
    base = source_fingerprint(project, force=True)
    (src / "new.py").unlink()
    assert source_fingerprint(project, force=True) != base


def test_fingerprint_ignores_ignored_and_generated_files(tmp_path: Path) -> None:
    project = init_workspace(tmp_path / "app")
    src = project / "src"
    src.mkdir()
    (src / "app.py").write_text("print('one')\n", encoding="utf-8")
    (project / ".gitignore").write_text("generated/\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    base = source_fingerprint(project, force=True)
    generated = project / "generated"
    generated.mkdir()
    (generated / "out.py").write_text("print('generated')\n", encoding="utf-8")
    deps = project / "node_modules"
    deps.mkdir()
    (deps / "dep.js").write_text("module.exports = {}\n", encoding="utf-8")
    assert source_fingerprint(project, force=True) == base


def test_fingerprint_walks_a_tree_without_git(tmp_path: Path) -> None:
    project = init_workspace(tmp_path / "app")
    src = project / "src"
    src.mkdir()
    (src / "app.py").write_text("print('one')\n", encoding="utf-8")
    base = source_fingerprint(project, force=True)
    assert base
    (src / "app.py").write_text("print('two')\n", encoding="utf-8")
    assert source_fingerprint(project, force=True) != base


def test_map_timeout_env_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    from lore.setup.graph_job import build_timeout

    monkeypatch.setenv("LORE_MAP_TIMEOUT", "0")
    assert build_timeout() == 1.0
    monkeypatch.setenv("LORE_MAP_TIMEOUT", "99999")
    assert build_timeout() == 3600.0
    monkeypatch.setenv("LORE_MAP_TIMEOUT", "junk")
    assert build_timeout() == 600.0
    monkeypatch.delenv("LORE_MAP_TIMEOUT")
    assert build_timeout() == 600.0


def test_extraction_timeout_fails_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_build: Path
) -> None:
    project = init_workspace(tmp_path / "app")
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    monkeypatch.setenv("LORE_MAP_TIMEOUT", "1")
    monkeypatch.setenv("LORE_FAKE_GRAPHIFY_SLEEP", "5")
    status = map_worker.run(project, "job-7")
    assert status["state"] == "failed"
    assert status["error_code"] == "timeout"


def test_two_workers_extract_once(tmp_path: Path, real_build: Path) -> None:
    project = init_workspace(tmp_path / "app")
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    marker = tmp_path / "extracts.txt"
    env = dict(os.environ)
    env["LORE_FAKE_GRAPHIFY_MARKER"] = str(marker)
    env["LORE_FAKE_GRAPHIFY_SLEEP"] = "1"
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "lore.map_worker",
                "--project",
                str(project),
                "--job",
                f"job-{index}",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for index in range(2)
    ]
    for proc in procs:
        proc.wait(timeout=60)
    assert all(proc.returncode == 0 for proc in procs)
    assert marker.read_text(encoding="utf-8").count("extract") == 1
    assert read_status(project)["state"] == "ready"


def test_killed_worker_recovers_as_interrupted(
    tmp_path: Path, real_build: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = init_workspace(tmp_path / "app")
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    monkeypatch.setenv("LORE_FAKE_GRAPHIFY_SLEEP", "30")
    from lore.setup.graph_job import start_build

    started = start_build(project)
    assert started["state"] == "running"
    pid = int(started["pid"])
    if os.name == "nt":
        os.kill(pid, signal.SIGTERM)
    else:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    _wait_for(lambda: read_status(project)["state"] == "interrupted")
    assert read_status(project)["state"] == "interrupted"
    monkeypatch.delenv("LORE_FAKE_GRAPHIFY_SLEEP")
    retry = start_build(project, force=True)
    assert retry["state"] in {"running", "ready"}
    _wait_for(lambda: read_status(project)["state"] == "ready")


def test_cli_map_waits_for_the_build(tmp_path: Path, real_build: Path) -> None:
    project = init_workspace(tmp_path / "app")
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    env = dict(os.environ)
    env["LORE_FAKE_GRAPHIFY_SLEEP"] = "2"
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "lore", "map", str(project)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    elapsed = time.monotonic() - started
    assert proc.returncode == 0
    assert "ready" in proc.stdout
    assert elapsed >= 2
    assert read_status(project)["state"] == "ready"


def test_cli_map_reports_extraction_failure(tmp_path: Path, real_build: Path) -> None:
    project = init_workspace(tmp_path / "app")
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    env = dict(os.environ)
    env["LORE_FAKE_GRAPHIFY_FAIL"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "lore", "map", str(project)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 1
    assert "failed" in proc.stdout
    assert "fake extract failed" in proc.stderr
    assert read_status(project)["state"] == "failed"
    assert "fake extract failed" in read_status(project)["error"]


def test_worker_keeps_last_good_graph_on_malformed_structure(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    project = _project(tmp_path)
    before = graph_file(project).read_text(encoding="utf-8")
    for index, damage in enumerate(
        [
            {"nodes": "oops"},
            {"nodes": None},
            {"links": "not-a-list"},
            {"nodes": ["not-a-dict"]},
            {"nodes": [{"label": "no-id.py", "source_file": "src/no_id.py"}]},
        ]
    ):

        assert isinstance(damage, dict)

        def nasty(source: Path, out: Path, damage: dict[str, Any] = damage) -> None:
            target = out / "graphify-out"
            target.mkdir(parents=True, exist_ok=True)
            data = json.loads(before)
            data.update(damage)
            (target / "graph.json").write_text(json.dumps(data), encoding="utf-8")

        status = map_worker.run(project, f"job-bad-{index}", extract=nasty)
        assert status["state"] == "failed", damage
        assert status["error_code"] == "invalid_graph", damage
        assert graph_file(project).read_text(encoding="utf-8") == before


def test_stale_html_is_not_served_as_current(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    from lore.core.graph import graph_html, html_current

    project = _project(tmp_path)
    status = map_worker.run(
        project, "job-old", extract=_fixture_extractor(graph_file(project))
    )
    assert status["state"] == "ready"
    assert html_current(project)

    def no_html(source: Path, out: Path) -> None:
        target = out / "graphify-out"
        target.mkdir(parents=True, exist_ok=True)
        data = json.loads(graph_file(project).read_text(encoding="utf-8"))
        (target / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    status = map_worker.run(project, "job-new", extract=no_html)
    assert status["state"] == "ready"
    assert "html_generation" not in status
    assert graph_html(project).is_file()
    assert not html_current(project)


def test_scheduler_race_never_replaces_a_rival(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_build: Path
) -> None:
    """Caller A parks inside start_build while caller B builds; A must not clobber B."""
    import threading

    from lore.setup import graph_job

    project = _project(tmp_path)
    spawned = threading.Event()
    allow_spawn = threading.Event()

    class ParkedProc:
        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def parked_spawn(project_arg: Path, job: str) -> Any:
        spawned.set()
        allow_spawn.wait(timeout=30)
        return ParkedProc()

    monkeypatch.setattr(graph_job, "_spawn_worker", parked_spawn)
    outcome: dict[str, Any] = {}

    def call() -> None:
        outcome["status"] = graph_job.start_build(project, force=True)

    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    assert spawned.wait(timeout=30)
    rival = map_worker.run(
        project, "job-b", extract=_fixture_extractor(graph_file(project))
    )
    assert rival["state"] == "ready"
    allow_spawn.set()
    thread.join(timeout=30)
    assert not thread.is_alive()
    status_a = outcome["status"]
    assert status_a["state"] == "ready"
    assert status_a["job_id"] == "job-b"
    assert read_status(project)["job_id"] == "job-b"


def test_scheduler_failure_write_respects_a_landed_generation(
    tmp_path: Path, enable_map: list[dict[str, Any]]
) -> None:
    from lore.core.graph import _read_status, status_file, write_status
    from lore.setup import graph_job

    project = _project(tmp_path)
    initial_raw = _read_status(status_file(project))
    rival = {"state": "ready", "job_id": "job-b", "finished_at": "now"}
    write_status(project, rival)
    result = graph_job._write_failed(project, "job-a", "worker_exit", "died", initial_raw)
    assert result["job_id"] == "job-b"
    assert read_status(project)["job_id"] == "job-b"

    result = graph_job._write_failed(project, "job-a", "worker_exit", "died", dict(rival))
    assert result["state"] == "failed"
    assert read_status(project)["job_id"] == "job-a"


def test_coalescer_merges_pending_onto_a_stale_running_status(
    tmp_path: Path, enable_map: list[dict[str, Any]], fake_graphify: Path
) -> None:
    from lore.core.graph import status_file, write_status
    from lore.setup.graph_job import ensure_fresh

    project = _project(tmp_path)
    write_status(
        project,
        {"state": "running", "job_id": "dead", "pid": 424242, "started_ts": 1.0},
    )
    note = ensure_fresh(project, now=lambda: 0.0)
    assert note == "The map will refresh shortly."
    raw = json.loads(status_file(project).read_text(encoding="utf-8"))
    assert raw["seen_fingerprint"]
    assert enable_map == []
    note = ensure_fresh(project, now=lambda: 91.0)
    assert note == "The map is building."
    assert len(enable_map) == 1


def test_concurrent_start_build_callers_extract_once(
    tmp_path: Path, real_build: Path
) -> None:
    project = init_workspace(tmp_path / "app")
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    marker = tmp_path / "extracts.txt"
    env = dict(os.environ)
    env["LORE_FAKE_GRAPHIFY_MARKER"] = str(marker)
    env["LORE_FAKE_GRAPHIFY_SLEEP"] = "1"
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from lore.setup.graph_job import start_build\n"
        "print(json.dumps(start_build(Path(sys.argv[1]), force=True)))\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(project)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
        results.append(json.loads(out.strip().splitlines()[-1]))
    assert all(
        str(status.get("state")) in {"running", "ready"} for status in results
    ), results
    _wait_for(lambda: read_status(project)["state"] == "ready")
    assert marker.read_text(encoding="utf-8").count("extract") == 1


def test_initiator_exits_while_the_detached_worker_finishes(
    tmp_path: Path, real_build: Path
) -> None:
    project = init_workspace(tmp_path / "app")
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    env = dict(os.environ)
    env["LORE_FAKE_GRAPHIFY_SLEEP"] = "2"
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from lore.setup.graph_job import start_build\n"
        "start_build(Path(sys.argv[1]), force=True)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, str(project)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    _wait_for(lambda: read_status(project)["state"] == "ready", attempts=400)
    assert graph_file(project).is_file()


def test_graphify_override_py_command_and_missing_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lore.setup import graph_job

    assert graph_job._graphify_cmd(tmp_path / "x.py") == [
        sys.executable,
        str(tmp_path / "x.py"),
    ]
    assert graph_job._graphify_cmd(tmp_path / "graphify") == [str(tmp_path / "graphify")]
    monkeypatch.setenv("LORE_MAP_ENABLED", "1")
    monkeypatch.setenv("LORE_GRAPHIFY", str(tmp_path / "missing.py"))
    capability = graph_job.map_capability()
    assert capability == {"available": False, "reason": "missing"}


def test_graphify_version_probe_timeout_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lore.core import graph_fingerprint as fingerprint

    exe = tmp_path / "graphify.py"
    exe.write_text(
        "import sys, time\n"
        "if sys.argv[1:] and sys.argv[1] == '--version':\n"
        "    time.sleep(30)\n"
        "    print('graphify 0.0.0-test')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LORE_MAP_ENABLED", "1")
    monkeypatch.setenv("LORE_GRAPHIFY", str(exe))
    monkeypatch.setattr(fingerprint, "VERSION_TIMEOUT", 0.5)
    fingerprint._graphify_version.cache_clear()
    started = time.monotonic()
    assert fingerprint.graphify_version() == ""
    assert time.monotonic() - started < 15


def test_map_lock_contention_and_context_manager(tmp_path: Path) -> None:
    path = tmp_path / ".lore" / "map.lock"
    first = MapLock(path)
    assert first.acquire()
    try:
        assert first.locked()
        assert MapLock(path).acquire() is False
        with pytest.raises(BlockingIOError), MapLock(path):
            pass
    finally:
        first.release()
    with MapLock(path) as third:
        assert third.locked()


def test_map_lock_open_failure_raises_oserror(tmp_path: Path) -> None:
    project = tmp_path / "app"
    project.mkdir()
    (project / ".lore").write_text("not a directory", encoding="utf-8")
    with pytest.raises(OSError):
        MapLock(project / ".lore" / "map.lock").acquire()


def test_fingerprint_skips_hidden_traversal_and_symlinks(tmp_path: Path) -> None:
    from lore.core.graph_fingerprint import _allowed_source, _walk_files

    project = tmp_path / "app"
    (project / "src").mkdir(parents=True)
    (project / "src" / "ok.py").write_text("x\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.py").write_text("x\n", encoding="utf-8")
    (project / "linkdir").symlink_to(outside, target_is_directory=True)
    (project / "src" / "linked.py").symlink_to(outside / "evil.py")
    assert _walk_files(project) == ["src/ok.py"]
    assert _allowed_source(project, "./src/ok.py")
    assert not _allowed_source(project, "../a.py")
    assert not _allowed_source(project, "./../a.py")
    assert not _allowed_source(project, ".hidden/a.py")
    assert not _allowed_source(project, "src/.secret.py")
    assert not _allowed_source(project, "src/linked.py")

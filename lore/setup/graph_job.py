"""Schedule map builds and read canonical status.

Explicit requests (`lore-solo map`, `map_codebase`, the setup build button) go
through `start_build`, which spawns `python -m lore.map_worker` and returns
after a bounded startup acknowledgment. Automatic refresh goes through
`ensure_fresh`, which coalesces source-fingerprint changes and suppresses
repeated failures for an unchanged tree.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lore.core.graph import (
    BUILDING_NOTE,
    _read_status,
    lock_file,
    log_file,
    map_is_stale,
    newest_source_mtime,
    read_status,
    status_file,
    write_status,
)

PENDING_NOTE = "The map will refresh shortly."
QUIET_SECONDS = 45.0
CEILING_SECONDS = 90.0
ACK_SECONDS = 5.0
LOG_LIMIT_BYTES = 256 * 1024
MISSING_MAP_MESSAGE = (
    "Graphify is not installed in this Lore environment. "
    "Run: lore-solo install --map"
)
DISABLED_MAP_MESSAGE = "Mapping is disabled by LORE_MAP_ENABLED."

Clock = Callable[[], float]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def map_disabled() -> bool:
    raw = os.environ.get("LORE_MAP_ENABLED", "").strip().lower()
    return raw in {"0", "false", "off", "no"}


def map_capability() -> dict[str, Any]:
    if map_disabled():
        return {"available": False, "reason": "disabled"}
    try:
        _graphify()
    except RuntimeError:
        return {"available": False, "reason": "missing"}
    return {"available": True, "reason": ""}


def build_timeout() -> float:
    raw = os.environ.get("LORE_MAP_TIMEOUT", "").strip()
    if not raw:
        return 600.0
    try:
        value = float(raw)
    except ValueError:
        return 600.0
    if not math.isfinite(value):
        return 600.0
    return min(3600.0, max(1.0, value))


def _graphify_override() -> str:
    return os.environ.get("LORE_GRAPHIFY", "").strip()


def _graphify() -> Path:
    override = _graphify_override()
    if override:
        exe = Path(override)
        if not exe.is_file():
            raise RuntimeError(MISSING_MAP_MESSAGE)
        return exe
    names = ("graphify.exe", "graphify") if os.name == "nt" else ("graphify",)
    for name in names:
        beside = Path(sys.executable).with_name(name)
        if beside.is_file():
            return beside
    found = shutil.which("graphify")
    if found is not None:
        return Path(found)
    raise RuntimeError(MISSING_MAP_MESSAGE)


def _graphify_cmd(exe: Path) -> list[str]:
    if exe.suffix.lower() == ".py":
        return [sys.executable, str(exe)]
    return [str(exe)]


def run_graphify(source: Path, out: Path, timeout: float | None = None) -> None:
    """Extract `source` into `out/graphify-out` and export the HTML view."""
    exe = _graphify()
    try:
        extract = subprocess.run(
            [*_graphify_cmd(exe), "extract", str(source), "--code-only", "--out", str(out)],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The codebase map timed out.") from exc
    if extract.returncode != 0:
        detail = (extract.stderr or extract.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "The codebase map could not be built."
        raise RuntimeError(message)
    graph = out / "graphify-out" / "graph.json"
    if not graph.is_file():
        raise RuntimeError("The map finished without a graph file.")
    html = out / "graphify-out" / "graph.html"
    if not html.is_file():
        try:
            subprocess.run(
                [*_graphify_cmd(exe), "export", "html", "--graph", str(graph)],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            pass


def ensure_fresh(project: Path, *, now: Clock | None = None) -> str | None:
    """Schedule a build when the map is missing or stale. Return a note, or None.

    Automatic work is request-driven: a failed build is not retried until the
    source fingerprint changes, and rebuilds of an existing map wait for a
    quiet window (or a ceiling) so edit bursts coalesce into one run.
    """
    if not map_capability()["available"]:
        return None
    clock = now or time.time
    status = read_status(project)
    state = str(status.get("state") or "")
    if state == "running":
        return BUILDING_NOTE
    from lore.core.graph_fingerprint import source_fingerprint

    fingerprint = source_fingerprint(project)
    if state == "failed" and status.get("source_fingerprint") == fingerprint:
        return str(status.get("error") or "The map failed.")
    graph = project / "graphify-out" / "graph.json"
    if not map_is_stale(project, current=fingerprint):
        return None

    has_sources = newest_source_mtime(project) is not None
    if not has_sources and not graph.is_file():
        return None

    # First map for a tree with sources: start immediately.
    if not graph.is_file():
        start_build(project)
        return BUILDING_NOTE

    return _coalesce_rebuild(project, status, fingerprint, clock())


def _coalesce_rebuild(
    project: Path,
    status: dict[str, Any],
    fingerprint: str,
    moment: float,
) -> str:
    from lore.core.map_lock import MapLock

    del status
    lock = MapLock(lock_file(project))
    if not lock.acquire():
        return BUILDING_NOTE
    try:
        status = _read_status(status_file(project))
        if not status:
            status = {"state": "missing"}
        seen = str(status.get("seen_fingerprint") or "")
        pending_since = status.get("pending_since")
        quiet_since = status.get("quiet_since")
        if pending_since is None or seen != fingerprint:
            write_status(
                project,
                {
                    **status,
                    "pending_since": moment if pending_since is None else float(pending_since),
                    "quiet_since": moment,
                    "seen_fingerprint": fingerprint,
                },
            )
            return PENDING_NOTE
        quiet_start = float(quiet_since if quiet_since is not None else pending_since)
        burst_start = float(pending_since)
        due = (moment - quiet_start) >= QUIET_SECONDS or (moment - burst_start) >= CEILING_SECONDS
    finally:
        lock.release()
    if due:
        start_build(project)
        return BUILDING_NOTE
    return PENDING_NOTE


def start_build(
    project: Path,
    status_path: Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Schedule a worker and return once the build is acknowledged.

    `status_path` is a deprecated compatibility input; the canonical build
    identity is always the resolved project. Returns the canonical status.
    """
    del status_path
    project = project.resolve()
    capability = map_capability()
    if not capability["available"]:
        return {
            "state": "unavailable",
            "reason": capability["reason"],
            "time": _now(),
        }
    current = read_status(project)
    if str(current.get("state") or "") == "running":
        return current

    from lore.core.graph_fingerprint import source_fingerprint

    if (
        not force
        and str(current.get("state") or "") == "failed"
        and current.get("source_fingerprint") == source_fingerprint(project, force=True)
    ):
        return current
    initial = current
    initial_raw = _read_status(status_file(project))
    job_id = uuid.uuid4().hex
    try:
        proc = _spawn_worker(project, job_id)
    except OSError as exc:
        return _write_failed(
            project,
            job_id,
            "spawn_failed",
            str(exc) or "The map worker could not start.",
            initial_raw,
        )
    return _await_ack(project, job_id, proc, initial, initial_raw)


_GENERATION_KEYS = ("state", "job_id", "finished_at", "error_code")


def _same_generation(latest: dict[str, Any], initial: dict[str, Any]) -> bool:
    return all(latest.get(key) == initial.get(key) for key in _GENERATION_KEYS)


def _write_failed(
    project: Path,
    job_id: str,
    code: str,
    message: str,
    initial_raw: dict[str, Any],
) -> dict[str, Any]:
    """Persist a scheduler failure only while no newer build owns the status."""
    from lore.core.map_lock import MapLock

    lock = MapLock(lock_file(project))
    if not lock.acquire():
        return read_status(project)
    try:
        latest = _read_status(status_file(project))
        if not _same_generation(latest, initial_raw):
            return read_status(project)
        failed = {
            **latest,
            "state": "failed",
            "job_id": job_id,
            "error_code": code,
            "error": message[:500],
            "finished_at": _now(),
        }
        write_status(project, failed)
        return failed
    finally:
        lock.release()


def _await_ack(
    project: Path,
    job_id: str,
    proc: subprocess.Popen[bytes],
    initial: dict[str, Any],
    initial_raw: dict[str, Any],
) -> dict[str, Any]:
    """Return when the canonical status names this job, or a rival took over."""
    deadline = time.monotonic() + ACK_SECONDS
    while time.monotonic() < deadline:
        status = read_status(project)
        if str(status.get("job_id")) == job_id:
            return status
        if not _same_generation(status, initial):
            return status
        if proc.poll() is not None:
            status = read_status(project)
            if str(status.get("job_id")) == job_id:
                return status
            if not _same_generation(status, initial):
                return status
            result = _write_failed(
                project,
                job_id,
                "worker_exit",
                "The map worker exited before it could start.",
                initial_raw,
            )
            if str(result.get("job_id")) == job_id or not _same_generation(result, initial):
                return result
        time.sleep(0.05)
    _terminate(proc)
    return _write_failed(
        project,
        job_id,
        "worker_start_timeout",
        "The map worker did not acknowledge the build in time.",
        initial_raw,
    )


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except OSError:
            pass


def _spawn_worker(project: Path, job_id: str) -> subprocess.Popen[bytes]:
    log = log_file(project)
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        if log.stat().st_size > LOG_LIMIT_BYTES:
            log.write_bytes(log.read_bytes()[-LOG_LIMIT_BYTES // 2 :])
    except OSError:
        pass
    handle = open(log, "ab")  # noqa: SIM115 - ownership moves to the worker process
    args = [sys.executable, "-m", "lore.map_worker", "--project", str(project), "--job", job_id]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": handle,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(args, **kwargs)
    finally:
        handle.close()


def wait_for_build(project: Path, status: dict[str, Any]) -> dict[str, Any]:
    """Foreground wait for a terminal state after `start_build`."""
    project = project.resolve()
    current = status
    deadline = time.monotonic() + build_timeout() + 30.0
    while str(current.get("state") or "") == "running" and time.monotonic() < deadline:
        time.sleep(0.25)
        current = read_status(project)
    if str(current.get("state") or "") == "running":
        return {
            **current,
            "state": "failed",
            "error_code": "timeout",
            "error": "The map build timed out.",
            "finished_at": _now(),
        }
    return current

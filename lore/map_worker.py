"""Map build worker. Spawned detached as `python -m lore.map_worker`.

The worker holds the per-project lock for the whole build, extracts into a
temporary output directory on the same filesystem, validates the result, then
atomically publishes `graphify-out/graph.json` and the status file.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ERROR_LIMIT = 500
DEFAULT_TIMEOUT = 600.0

Extractor = Callable[[Path, Path], None]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def extraction_timeout() -> float:
    raw = os.environ.get("LORE_MAP_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT
    if not math.isfinite(value):
        return DEFAULT_TIMEOUT
    return min(3600.0, max(1.0, value))


def _default_extractor(timeout: float) -> Extractor:
    def extract(source: Path, out: Path) -> None:
        from lore.setup.graph_job import run_graphify

        run_graphify(source, out, timeout=timeout)

    return extract


def _validate_graph(path: Path, project: Path) -> dict[str, Any]:
    """Parse and sanity-check extracted output before it can replace the map."""
    from lore.core.graph import KNOWN_SCHEMA, _contained, _version

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("The map output is not readable JSON.") from exc
    if not isinstance(data, dict) or _version(data) not in KNOWN_SCHEMA:
        raise ValueError("The map used a format Lore does not read yet.")
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        raise TypeError("The map nodes are not a list.")
    links = data.get("links", data.get("edges", []))
    if not isinstance(links, list):
        raise TypeError("The map links are not a list.")
    for node in nodes:
        if not isinstance(node, dict) or not node.get("id"):
            raise ValueError("The map contains an invalid node.")
        raw = str(node.get("source_file") or "")
        if raw and not _contained(project, raw):
            raise ValueError(f"The map references a file outside the project: {raw}")
    return data


def _publish_json(out_dir: Path, data: dict[str, Any], target: Path) -> None:
    handle, tmp_name = tempfile.mkstemp(dir=out_dir, prefix=".graph-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(data, indent=2) + "\n")
        os.replace(tmp_name, target)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _publish_html(produced: Path, target: Path) -> bool:
    if not produced.is_file():
        return False
    try:
        os.replace(produced, target)
    except OSError:
        return False
    return True


def run(project: Path, job_id: str, *, extract: Extractor | None = None) -> dict[str, Any]:
    """Build one map. Returns the final status; a rival lock holder wins."""
    from lore.core.graph import git_head, graph_file, graph_html, lock_file, write_status
    from lore.core.graph_fingerprint import source_fingerprint
    from lore.core.map_lock import MapLock
    from lore.setup.graph_job import map_disabled

    if map_disabled():
        return {"state": "unavailable", "reason": "disabled", "job_id": job_id}
    project = project.resolve()
    lock = MapLock(lock_file(project))
    if not lock.acquire():
        return {"state": "skipped", "job_id": job_id}
    try:
        status: dict[str, Any] = {
            "state": "running",
            "job_id": job_id,
            "pid": os.getpid(),
            "started_at": _now(),
            "started_ts": time.time(),
        }
        write_status(project, status)
        try:
            extractor = extract or _default_extractor(extraction_timeout())
            before = source_fingerprint(project, force=True)
            status["source_fingerprint"] = before
            out_dir = project / "graphify-out"
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix=".map-", dir=out_dir))
            try:
                extractor(project, tmp)
                produced = tmp / "graphify-out" / "graph.json"
                if not produced.is_file():
                    raise RuntimeError("The map finished without a graph file.")
                data = _validate_graph(produced, project)
                after = source_fingerprint(project, force=True)
                commit = git_head(project)
                if commit:
                    data["built_at_commit"] = commit
                data["source_fingerprint"] = before
                data["map_generation"] = job_id
                _publish_json(out_dir, data, graph_file(project))
                html_ok = _publish_html(tmp / "graphify-out" / "graph.html", graph_html(project))
                status = {
                    **status,
                    "state": "ready",
                    "finished_at": _now(),
                    "schema_version": _safe_version(data),
                    "stale": after != before,
                }
                if html_ok:
                    status["html_generation"] = job_id
            except Exception as exc:  # noqa: BLE001 - any map failure must settle the status file
                status = {
                    **status,
                    "state": "failed",
                    "finished_at": _now(),
                    "error_code": _error_code(exc),
                    "error": (str(exc) or "The codebase map failed.")[:ERROR_LIMIT],
                }
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001 - fingerprint or staging failures settle failed
            status = {
                **status,
                "state": "failed",
                "finished_at": _now(),
                "error_code": _error_code(exc),
                "error": (str(exc) or "The codebase map failed.")[:ERROR_LIMIT],
            }
        write_status(project, status)
        return status
    finally:
        lock.release()


def _safe_version(data: dict[str, Any]) -> Any:
    from lore.core.graph import _version

    return _version(data)


def _error_code(exc: Exception) -> str:
    text = str(exc).lower()
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if isinstance(exc, (ValueError, TypeError, json.JSONDecodeError)):
        return "invalid_graph"
    return "extract_failed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lore.map_worker")
    parser.add_argument("--project", required=True)
    parser.add_argument("--job", required=True)
    args = parser.parse_args(argv)
    status = run(Path(args.project), args.job)
    return 0 if status.get("state") in {"ready", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

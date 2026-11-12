"""Read the codebase map Graphify left in `graphify-out/`."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from lore.core.budget import count_tokens
from lore.core.graph_fingerprint import CODE_SUFFIXES as _CODE_SUFFIXES
from lore.core.graph_fingerprint import SKIP_DIRS as _SKIP_DIRS

KNOWN_SCHEMA = {1, "1"}
MAP_NOTE = "Map this project"
BUILDING_NOTE = "The map is building."
LOCATE_FILES = 8
LOCATE_TOKENS = 400
_HUBS = 3
STARTUP_GRACE_SECONDS = 15.0


def status_file(project: Path) -> Path:
    return project / ".lore" / "graph-status.json"


def lock_file(project: Path) -> Path:
    return project / ".lore" / "map.lock"


def log_file(project: Path) -> Path:
    return project / ".lore" / "map.log"


def graph_file(project: Path) -> Path:
    return project / "graphify-out" / "graph.json"


def graph_html(project: Path) -> Path:
    return project / "graphify-out" / "graph.html"


def _read_status(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"state": "failed", "error_code": "status_read", "error": "The status file could not be read."}
    return loaded if isinstance(loaded, dict) else {}


def write_status(project: Path, payload: dict[str, Any]) -> None:
    """Atomically replace the canonical status file."""
    import tempfile

    path = status_file(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=".graph-status-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2) + "\n")
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_status(project: Path, legacy: Path | None = None) -> dict[str, Any]:
    """Canonical map status with worker-liveness recovery.

    A `running` record only stays running while the build lock is held or the
    just-scheduled worker is still inside its startup grace window. Anything
    else becomes `interrupted` and can be retried explicitly.
    """
    raw = _read_status(status_file(project))
    if not raw and legacy is not None:
        raw = _read_status(legacy)
    status = dict(raw) if raw else {"state": "missing"}
    if str(status.get("state") or "") != "running":
        return status
    from lore.core.map_lock import lock_held

    if lock_held(lock_file(project)):
        return status
    if status.get("pid") is None:
        started = status.get("started_ts")
        try:
            age = time.time() - float(started) if started is not None else None
        except (TypeError, ValueError):
            age = None
        if age is not None and age <= STARTUP_GRACE_SECONDS:
            return status
    return {
        **status,
        "state": "interrupted",
        "error_code": status.get("error_code") or "worker_exit",
        "error": str(status.get("error") or "The map worker stopped before finishing."),
    }


def slice_for(project: Path, file_path: str, notes: list[str]) -> list[dict[str, Any]]:
    path = project / "graphify-out" / "graph.json"
    if not path.is_file():
        notes.append(MAP_NOTE)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        notes.append(MAP_NOTE)
        return []
    if not isinstance(data, dict) or _version(data) not in KNOWN_SCHEMA:
        notes.append(MAP_NOTE)
        return []
    nodes = [node for node in data.get("nodes", []) if isinstance(node, dict) and node.get("id")]
    links = data.get("links", data.get("edges", []))
    if not isinstance(links, list):
        links = []
    by_id = {str(node["id"]): node for node in nodes}
    if file_path:
        chosen = _neighborhood(project, nodes, links, by_id, file_path)
    else:
        chosen = _hubs(nodes, links)
    return [_item(project, node, links, by_id) for node in chosen]


def summarize(project: Path, legacy: Path | None = None) -> dict[str, Any]:
    """Status plus a short list of links for the codebase page."""
    status = map_status(project, legacy=legacy)
    path = project / "graphify-out" / "graph.json"
    rows: list[dict[str, str]] = []
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            labels = {
                str(node.get("id")): str(node.get("label") or node.get("id"))
                for node in data.get("nodes", [])
                if isinstance(node, dict)
            }
            links = data.get("links", data.get("edges", []))
            if isinstance(links, list):
                for link in links:
                    if not isinstance(link, dict):
                        continue
                    confidence = str(link.get("confidence") or "")
                    if confidence not in {"EXTRACTED", "INFERRED"}:
                        continue
                    rows.append(
                        {
                            "node": labels.get(str(link.get("source")), str(link.get("source"))),
                            "to": labels.get(str(link.get("target")), str(link.get("target"))),
                            "relation": str(link.get("relation") or ""),
                            "confidence": confidence,
                        }
                    )
                    if len(rows) >= 12:
                        break
    status["links"] = rows
    return status


def _unrelative(raw: str) -> str:
    value = raw.replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def _contained(project: Path, rel: str) -> bool:
    normalized = _unrelative(rel)
    if not normalized or PureWindowsPath(normalized).drive:
        return False
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    try:
        (project / normalized).resolve().relative_to(project.resolve())
    except (OSError, ValueError):
        return False
    return True


def _version(data: dict[str, Any]) -> Any:
    if "schema_version" in data:
        return data["schema_version"]
    graph = data.get("graph")
    if isinstance(graph, dict):
        return graph.get("schema_version")
    return None


def _neighborhood(
    project: Path,
    nodes: list[dict[str, Any]],
    links: list[Any],
    by_id: dict[str, dict[str, Any]],
    file_path: str,
) -> list[dict[str, Any]]:
    matches = [node for node in nodes if _same_file(project, node, file_path)]
    if not matches:
        return []
    filename = Path(file_path).name
    primary = next((node for node in matches if node.get("label") == filename), matches[0])
    ordered = [primary]
    seen = {str(primary["id"])}
    for link in links:
        if not isinstance(link, dict) or not _is_import_or_call(str(link.get("relation") or "")):
            continue
        source = str(link.get("source"))
        target = str(link.get("target"))
        other = ""
        if source == str(primary["id"]):
            other = target
        elif target == str(primary["id"]):
            other = source
        if other and other not in seen and other in by_id:
            seen.add(other)
            ordered.append(by_id[other])
    return ordered


def _hubs(nodes: list[dict[str, Any]], links: list[Any]) -> list[dict[str, Any]]:
    degree: dict[str, int] = {str(node["id"]): 0 for node in nodes}
    for link in links:
        if not isinstance(link, dict):
            continue
        for end in (link.get("source"), link.get("target")):
            key = str(end)
            if key in degree:
                degree[key] += 1
    ranked = sorted(nodes, key=lambda node: (-degree[str(node["id"])], str(node["id"])))
    return ranked[:_HUBS]


def _item(
    project: Path,
    node: dict[str, Any],
    links: list[Any],
    by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    label = str(node.get("label") or node["id"])
    source = _source_path(node)
    if not _contained(project, source):
        source = ""
    bits: list[str] = []
    for link in links:
        if not isinstance(link, dict) or not _is_import_or_call(str(link.get("relation") or "")):
            continue
        source_id = str(link.get("source"))
        target_id = str(link.get("target"))
        if source_id != str(node["id"]) and target_id != str(node["id"]):
            continue
        other_id = target_id if source_id == str(node["id"]) else source_id
        other = by_id.get(other_id, {})
        other_label = str(other.get("label") or other_id)
        confidence = str(link.get("confidence") or "EXTRACTED")
        bits.append(f"{link.get('relation')} {other_label} ({confidence})")
    text = label if not bits else f"{label}: {', '.join(bits)}."
    return {
        "id": f"chunk:{node['id']}",
        "kind": "chunk",
        "role": "background",
        "authority": "unreviewed",
        "status": "unverified",
        "freshness": "current",
        "origin": "git_derived",
        "confidence": {"band": "high", "p": 0.9},
        "title": label,
        "text": text,
        "source": {"path": source, "anchor": "graph"},
    }


def _same_file(project: Path, node: dict[str, Any], file_path: str) -> bool:
    source = _source_path(node)
    if not source or not _contained(project, source):
        return False
    wanted = file_path.replace("\\", "/")
    if wanted.startswith("/"):
        try:
            wanted = Path(wanted).resolve().relative_to(project.resolve()).as_posix()
        except (OSError, ValueError):
            return False
    wanted = _unrelative(wanted)
    if ".." in PurePosixPath(wanted).parts:
        return False
    return source == wanted or source.endswith("/" + wanted)


def _is_import_or_call(relation: str) -> bool:
    name = relation.lower()
    return name.startswith(("import", "call"))


def built_at_commit(project: Path) -> str | None:
    path = project / "graphify-out" / "graph.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    direct = data.get("built_at_commit")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    graph = data.get("graph")
    if isinstance(graph, dict):
        nested = graph.get("built_at_commit")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return None


def git_head(project: Path) -> str | None:
    """HEAD when `project` itself is the git root.

    A copied folder inside some other repo must not inherit that repo's commit,
    or every temporary project would look stale.
    """
    try:
        top = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if top.returncode != 0 or not top.stdout.strip():
        return None
    try:
        if Path(top.stdout.strip()).resolve() != project.resolve():
            return None
    except OSError:
        return None
    try:
        head = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if head.returncode != 0:
        return None
    value = head.stdout.strip()
    return value or None


def newest_source_mtime(project: Path) -> float | None:
    newest: float | None = None
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS and not name.startswith(".")]
        for name in filenames:
            if Path(name).suffix.lower() not in _CODE_SUFFIXES:
                continue
            try:
                mtime = (Path(dirpath) / name).stat().st_mtime
            except OSError:
                continue
            if newest is None or mtime > newest:
                newest = mtime
    return newest


def map_is_stale(project: Path, *, current: str | None = None) -> bool:
    """True when the recorded source fingerprint no longer matches the tree.

    Legacy graphs carry no fingerprint and are stale once so they rebuild.
    `built_at_commit` stays in the graph as provenance but is never the only
    freshness signal.
    """
    data = _load(project)
    if data is None:
        return True
    recorded = str(data.get("source_fingerprint") or "")
    if not recorded:
        return True
    if current is None:
        from lore.core.graph_fingerprint import source_fingerprint

        current = source_fingerprint(project)
    return recorded != current


def map_status(project: Path, legacy: Path | None = None) -> dict[str, Any]:
    status = read_status(project, legacy=legacy)
    from lore.setup.graph_job import map_capability

    capability = map_capability()
    status["available"] = capability["available"]
    status["reason"] = capability["reason"]
    if capability["reason"] == "disabled" or (
        not capability["available"]
        and str(status.get("state") or "")
        in {
            "",
            "missing",
            "failed",
            "interrupted",
        }
    ):
        status["state"] = "unavailable"
    commit = built_at_commit(project)
    if commit:
        status["built_at_commit"] = commit
    return status


def html_current(project: Path) -> bool:
    """True when the published HTML matches the published map generation."""
    status = read_status(project)
    generation = status.get("html_generation")
    if not generation:
        return False
    data = _load(project)
    if not isinstance(data, dict):
        return False
    return bool(data.get("map_generation") == generation)


def map_data(project: Path) -> dict[str, Any]:
    """Advisory map metadata for a get_context result."""
    status = map_status(project)
    state = str(status.get("state") or "missing")
    return {
        "state": state,
        "stale": map_is_stale(project),
        "available": bool(status.get("available", True)),
        "advisory": True,
    }


def locate(project: Path, intent: str, file_path: str = "") -> dict[str, Any]:
    """Files a task should open, with the relation that justified each one.

    The raw graph is not returned. At most eight files, inside a small token budget.
    """
    notes: list[str] = []
    data = _load(project)
    if data is None:
        notes.append(MAP_NOTE)
        return _fit_files([], notes)
    nodes = [node for node in data.get("nodes", []) if isinstance(node, dict) and node.get("id")]
    links = data.get("links", data.get("edges", []))
    if not isinstance(links, list):
        links = []
    tokens = [token for token in re.findall(r"[a-z0-9]+", intent.lower()) if len(token) >= 2]
    by_id = {str(node["id"]): node for node in nodes}
    scores: dict[str, int] = {}
    labels: dict[str, str] = {}
    matched: set[str] = set()
    for node in nodes:
        source = _source_path(node)
        if not source or not _contained(project, source):
            continue
        hay = f"{source} {node.get('label') or ''}".lower()
        score = sum(1 for token in tokens if token in hay)
        if file_path and _same_file(project, node, file_path):
            score += 5
        if score <= 0:
            continue
        matched.add(str(node["id"]))
        scores[source] = scores.get(source, 0) + score
        label = str(node.get("label") or Path(source).name)
        filename = Path(source).name
        if source not in labels or label == filename:
            labels[source] = label
    chosen: list[dict[str, str]] = [
        {"path": path, "relation": "match", "label": labels.get(path, Path(path).name)}
        for path in sorted(scores, key=lambda item: (-scores[item], item))
    ]
    seen = {item["path"] for item in chosen}
    for link in links:
        if not isinstance(link, dict) or not _is_import_or_call(str(link.get("relation") or "")):
            continue
        source_id = str(link.get("source"))
        target_id = str(link.get("target"))
        if source_id not in matched and target_id not in matched:
            continue
        other_id = target_id if source_id in matched else source_id
        other = by_id.get(other_id, {})
        other_path = _source_path(other)
        if not other_path or not _contained(project, other_path) or other_path in seen:
            continue
        seen.add(other_path)
        chosen.append(
            {
                "path": other_path,
                "relation": str(link.get("relation") or ""),
                "label": str(other.get("label") or Path(other_path).name),
            }
        )
    return _fit_files(chosen, notes)


def _load(project: Path) -> dict[str, Any] | None:
    path = project / "graphify-out" / "graph.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or _version(data) not in KNOWN_SCHEMA:
        return None
    return data


def _source_path(node: dict[str, Any]) -> str:
    return _unrelative(str(node.get("source_file") or ""))


def _fit_files(files: list[dict[str, str]], notes: list[str]) -> dict[str, Any]:
    kept: list[dict[str, str]] = []
    omitted: list[str] = []
    used = count_tokens(" ".join(notes)) if notes else 0
    for item in files:
        if len(kept) >= LOCATE_FILES:
            omitted.append(item["path"])
            continue
        line = f"{item['path']} {item['relation']} {item['label']}"
        cost = count_tokens(line)
        if used + cost > LOCATE_TOKENS:
            omitted.append(item["path"])
            continue
        kept.append(item)
        used += cost
    return {
        "files": kept,
        "omitted": omitted,
        "notes": notes,
        "budget": {"limit": LOCATE_TOKENS, "used": used},
    }

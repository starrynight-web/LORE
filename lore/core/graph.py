"""Read the codebase map Graphify left in `graphify-out/`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KNOWN_SCHEMA = {1, "1"}
MAP_NOTE = "Map this project"
_HUBS = 3


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
    return [_item(node, links, by_id) for node in chosen]


def summarize(project: Path) -> dict[str, Any]:
    """Status plus a short list of links for the codebase page."""
    status_path = project / ".lore" / "graph-status.json"
    status: dict[str, Any] = {"state": "missing"}
    if status_path.is_file():
        try:
            loaded = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {"state": "failed", "error": "The status file could not be read."}
        if isinstance(loaded, dict):
            status = loaded
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


def _item(node: dict[str, Any], links: list[Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    label = str(node.get("label") or node["id"])
    bits: list[str] = []
    for link in links:
        if not isinstance(link, dict) or not _is_import_or_call(str(link.get("relation") or "")):
            continue
        source = str(link.get("source"))
        target = str(link.get("target"))
        if source != str(node["id"]) and target != str(node["id"]):
            continue
        other_id = target if source == str(node["id"]) else source
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
        "source": {"path": str(node.get("source_file") or ""), "anchor": "graph"},
    }


def _same_file(project: Path, node: dict[str, Any], file_path: str) -> bool:
    source = str(node.get("source_file") or "").replace("\\", "/").lstrip("./")
    if not source:
        return False
    wanted = file_path.replace("\\", "/")
    if wanted.startswith("/"):
        try:
            wanted = Path(wanted).resolve().relative_to(project.resolve()).as_posix()
        except ValueError:
            wanted = Path(wanted).name
    wanted = wanted.lstrip("./")
    return source == wanted or source.endswith("/" + wanted)


def _is_import_or_call(relation: str) -> bool:
    name = relation.lower()
    return name.startswith(("import", "call"))

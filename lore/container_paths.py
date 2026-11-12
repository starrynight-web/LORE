"""Translate paths between the host and the Lore container mounts.

Active only when ``LORE_CONTAINER=1``. The host wrapper exports
``LORE_HOST_WORKSPACE`` and ``LORE_HOST_LIBRARY`` with the original host
paths; inside the container those roots are mounted at ``/workspace`` and
``/library``. Pure stdlib so it works in every runtime Lore ships.
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

WORKSPACE_MOUNT = "/workspace"
LIBRARY_MOUNT = "/library"

_DRIVE = re.compile(r"^[A-Za-z]:")


class PathMappingError(ValueError):
    """A path cannot be mapped between the host and the container."""


def active() -> bool:
    return os.environ.get("LORE_CONTAINER", "").strip() == "1"


def _host_roots() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    workspace = os.environ.get("LORE_HOST_WORKSPACE", "").strip()
    if workspace:
        pairs.append((workspace, WORKSPACE_MOUNT))
    library = os.environ.get("LORE_HOST_LIBRARY", "").strip()
    if library:
        pairs.append((library, LIBRARY_MOUNT))
    return pairs


def _is_windows_path(raw: str) -> bool:
    if raw.startswith(("\\\\", "//")):
        return True
    if _DRIVE.match(raw):
        return True
    return "\\" in raw


def _parts(raw: str, windows: bool) -> tuple[bool, list[str]]:
    """(absolute, parts) for `raw`; raises on drive-relative input."""
    if windows:
        if _DRIVE.match(raw) and not (len(raw) >= 3 and raw[2] in "\\/"):
            raise PathMappingError(f"drive-relative path is not supported: {raw}")
        path = PureWindowsPath(raw)
        parts = list(path.parts)
        absolute = bool(parts and parts[0].endswith("\\"))
        if absolute and not path.drive:
            raise PathMappingError(f"drive-less rooted path is not supported: {raw}")
        return absolute, parts
    posix_path = PurePosixPath(raw)
    parts = list(posix_path.parts)
    absolute = bool(parts and parts[0] == "/")
    return absolute, parts


def _reject_particles(parts: list[str], raw: str) -> None:
    for part in parts:
        if part == "..":
            raise PathMappingError(f"parent components are not allowed: {raw}")
        if "\x00" in part or "\n" in part or "\r" in part:
            raise PathMappingError(f"invalid character in path: {raw!r}")


def _match_root(
    parts: list[str], root_parts: list[str], windows: bool
) -> list[str] | None:
    if len(parts) < len(root_parts):
        return None
    for want, got in zip(root_parts, parts):
        if windows:
            if want.casefold() != got.casefold():
                return None
        elif want != got:
            return None
    return parts[len(root_parts) :]


def _normalize_relative(parts: list[str]) -> str:
    kept = [part for part in parts if part != "."]
    if not kept:
        return "."
    return "/".join(kept)


def _join(runtime_root: str, parts: list[str]) -> str:
    if not parts:
        return runtime_root
    return runtime_root.rstrip("/") + "/" + "/".join(parts)


def _join_host(root: str, parts: list[str]) -> str:
    windows = _is_windows_path(root)
    if windows:
        base = PureWindowsPath(root)
        for part in parts:
            base = base / part
        return str(base)
    if not parts:
        return root
    return root.rstrip("/") + "/" + "/".join(parts)


def _map_host_to_runtime(raw: str) -> str:
    windows = _is_windows_path(raw)
    absolute, parts = _parts(raw, windows)
    _reject_particles(parts[1:] if absolute else parts, raw)
    if not absolute:
        return _normalize_relative(parts)
    runtime = WORKSPACE_MOUNT, LIBRARY_MOUNT
    if not windows:
        for mount in runtime:
            rest = _match_root(parts, list(PurePosixPath(mount).parts), windows=False)
            if rest is not None:
                return _join(mount, [p for p in rest if p != "."])
    best: tuple[int, str, list[str]] | None = None
    for host_root, runtime_root in _host_roots():
        if _is_windows_path(host_root) != windows:
            continue
        _, root_parts = _parts(host_root, windows)
        rest = _match_root(parts, root_parts, windows)
        if rest is None:
            continue
        score = len(root_parts)
        if best is not None and best[0] == score:
            raise PathMappingError(f"ambiguous container mapping for {raw}")
        if best is None or score > best[0]:
            best = (score, runtime_root, rest)
    if best is None:
        raise PathMappingError(f"absolute path outside the container mounts: {raw}")
    return _join(best[1], [p for p in best[2] if p != "."])


def _map_runtime_to_host(raw: str) -> str:
    windows = _is_windows_path(raw)
    absolute, parts = _parts(raw, windows)
    _reject_particles(parts[1:] if absolute else parts, raw)
    if not absolute:
        return _normalize_relative(parts)
    if windows:
        for host_root, _mount in _host_roots():
            if not _is_windows_path(host_root):
                continue
            _, root_parts = _parts(host_root, windows)
            if _match_root(parts, root_parts, windows) is not None:
                return _join_host(host_root, [p for p in parts[len(root_parts):] if p != "."])
        raise PathMappingError(f"host path outside the mapped roots: {raw}")
    best: tuple[int, str, list[str]] | None = None
    for host_root, runtime_root in _host_roots():
        rest = _match_root(parts, list(PurePosixPath(runtime_root).parts), windows=False)
        if rest is not None:
            score = len(PurePosixPath(runtime_root).parts)
            if best is not None and best[0] == score:
                raise PathMappingError(f"ambiguous host mapping for {raw}")
            if best is None or score > best[0]:
                best = (score, host_root, rest)
            continue
        if _is_windows_path(host_root):
            continue
        _, root_parts = _parts(host_root, windows=False)
        if _match_root(parts, root_parts, windows=False) is not None:
            return _join_host(host_root, [p for p in parts[len(root_parts):] if p != "."])
    if best is None:
        raise PathMappingError(f"absolute path outside the mapped roots: {raw}")
    return _join_host(best[1], [p for p in best[2] if p != "."])


def to_runtime(raw: str) -> str:
    """Map a host path to its in-container form; native is identity."""
    if not raw or not active():
        return raw
    return _map_host_to_runtime(raw)


def to_host(raw: str) -> str:
    """Map an in-container path back to the host form; native is identity."""
    if not raw or not active():
        return raw
    return _map_runtime_to_host(raw)


def convert_result(node: Any, *, in_task: bool = False) -> Any:
    """Convert structured `path` fields and the task `file` echo to host form.

    Values that cannot be mapped stay unchanged so relative repository paths
    and unrelated text survive untouched.
    """
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if (
                key == "path" or (key == "file" and in_task)
            ) and isinstance(value, str):
                out[key] = _safe_host(value)
            elif key == "task" and isinstance(value, dict):
                out[key] = convert_result(value, in_task=True)
            else:
                out[key] = convert_result(value)
        return out
    if isinstance(node, list):
        return [convert_result(item) for item in node]
    return node


def _safe_host(value: str) -> str:
    try:
        return to_host(value)
    except PathMappingError:
        return value

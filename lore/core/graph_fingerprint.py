"""Content fingerprint of the sources a map was extracted from.

The fingerprint covers relevant repository-relative source paths and their
content hashes plus the extraction configuration and Graphify version. Git
trees use tracked and nonignored untracked files; other trees are walked with
the same generated/dependency/hidden exclusions Lore uses elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

CODE_SUFFIXES = {
    ".c",
    ".css",
    ".go",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scss",
    ".svelte",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".vue",
}
SKIP_DIRS = {
    ".git",
    ".lore",
    ".next",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "graphify-out",
    "node_modules",
}
EXTRACT_CONFIG = "extract --code-only"
CACHE_NAME = "map-fingerprint.json"


def cache_path(project: Path) -> Path:
    return project / ".lore" / CACHE_NAME


def graphify_version() -> str:
    """`graphify --version`. Empty when unavailable or mapping is disabled."""
    try:
        from lore.setup.graph_job import map_disabled
    except ImportError:
        return ""
    if map_disabled():
        return ""
    return _graphify_version()


VERSION_TIMEOUT = 15.0


@lru_cache(maxsize=1)
def _graphify_version() -> str:
    """Resolved once per process; tests may `cache_clear` when the exe changes."""
    try:
        from lore.setup.graph_job import _graphify, _graphify_cmd, _graphify_override
    except ImportError:
        return ""
    try:
        exe = _graphify()
    except RuntimeError:
        return ""
    if not _graphify_override():
        try:
            from importlib.metadata import PackageNotFoundError, version

            installed = version("graphifyy")
        except (PackageNotFoundError, OSError, RuntimeError):
            installed = ""
        if installed:
            return installed
    try:
        proc = subprocess.run(
            [*_graphify_cmd(exe), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=VERSION_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip().splitlines()[0].strip() if proc.returncode == 0 and proc.stdout.strip() else ""


def source_fingerprint(project: Path, *, force: bool = False) -> str:
    """Hex digest of relevant source paths, content, config, and tool version.

    Cached content hashes are reused when a file's stat triple is unchanged;
    `force` rehashes every file for an explicit build.
    """
    project = project.resolve()
    entries = _entries(project, force=force)
    digest = hashlib.sha256()
    for rel, sha in entries:
        digest.update(rel.encode("utf-8") + b"\0" + sha.encode("utf-8") + b"\0")
    digest.update(b"config\0" + EXTRACT_CONFIG.encode("utf-8"))
    digest.update(b"\0version\0" + graphify_version().encode("utf-8"))
    return digest.hexdigest()


def _entries(project: Path, *, force: bool) -> list[tuple[str, str]]:
    cache = _read_cache(project)
    files_cache = cache.get("files")
    previous: dict[str, Any] = files_cache if isinstance(files_cache, dict) else {}
    files = _git_files(project)
    if files is None:
        files = _walk_files(project)
    entries: list[tuple[str, str]] = []
    current: dict[str, list[Any]] = {}
    for rel in sorted(files):
        path = project / rel
        try:
            info = path.stat()
        except OSError:
            continue
        stat_key = [info.st_mtime_ns, info.st_size, info.st_ctime_ns]
        cached = previous.get(rel)
        sha: str | None
        if (
            not force
            and isinstance(cached, list)
            and len(cached) == 4
            and cached[:3] == stat_key
            and isinstance(cached[3], str)
        ):
            sha = cached[3]
        else:
            sha = _hash_file(path)
        if sha is None:
            continue
        entries.append((rel, sha))
        current[rel] = [*stat_key, sha]
    _write_cache(project, {"files": current})
    return entries


def _hash_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _git_files(project: Path) -> list[str] | None:
    """Tracked and nonignored untracked files, when `project` is the Git root."""
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
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(project),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    names = [name.decode("utf-8", "surrogateescape") for name in proc.stdout.split(b"\0") if name]
    return [rel for rel in names if _allowed_source(project, rel)]


def _walk_files(project: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(project, followlinks=False):
        dirnames[:] = [
            name for name in dirnames if name not in SKIP_DIRS and not name.startswith(".")
        ]
        for name in filenames:
            if name.startswith("."):
                continue
            path = Path(dirpath) / name
            try:
                rel = path.relative_to(project).as_posix()
            except ValueError:
                continue
            if _allowed_source(project, rel):
                found.append(rel)
    return found


def _allowed_source(project: Path, rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or PureWindowsPath(normalized).drive
        or pure.is_absolute()
        or ".." in pure.parts
    ):
        return False
    if any(part in SKIP_DIRS or part.startswith(".") for part in pure.parts):
        return False
    if pure.suffix.lower() not in CODE_SUFFIXES:
        return False
    path = project / normalized
    try:
        info = path.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    try:
        path.resolve().relative_to(project.resolve())
    except (OSError, ValueError):
        return False
    return True


def _read_cache(project: Path) -> dict[str, Any]:
    path = cache_path(project)
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_cache(project: Path, payload: dict[str, Any]) -> None:
    path = cache_path(project)
    tmp: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=".fingerprint-", suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload) + "\n")
        os.replace(tmp, path)
    except OSError:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass

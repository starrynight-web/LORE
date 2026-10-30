"""Find the project that contains a `.lore` folder."""

from __future__ import annotations

import os
import platform
from pathlib import Path


class LoreNotFound(Exception):
    """No `.lore` folder exists in this directory or any parent."""

    def __init__(self, start: Path) -> None:
        self.start = start
        super().__init__(f"No .lore folder in {start} or its parents.")


def workspace_root() -> Path:
    """The project the editor opened. Defaults to the current directory."""
    raw = os.environ.get("LORE_WORKSPACE", "")
    if raw:
        return Path(raw)
    return Path.cwd()


def default_library(system: str | None = None, home: Path | None = None) -> Path:
    """The persona library for this operating system.

    Linux uses `$XDG_DATA_HOME/lore` or `~/.local/share/lore`. macOS uses
    `~/Library/Application Support/Lore`. Windows uses `%APPDATA%\\Lore`.
    """
    kind = (system or platform.system()).lower()
    base = home if home is not None else Path.home()
    if kind.startswith("win"):
        appdata = os.environ.get("APPDATA", "")
        root = Path(appdata) if appdata and home is None else base / "AppData" / "Roaming"
        return root / "Lore"
    if kind.startswith("darwin"):
        return base / "Library" / "Application Support" / "Lore"
    data_home = os.environ.get("XDG_DATA_HOME", "")
    root = Path(data_home) if data_home and home is None else base / ".local" / "share"
    return root / "lore"


def library_root() -> Path:
    """Personas used when the open project does not keep its own."""
    raw = os.environ.get("LORE_LIBRARY", "")
    if raw:
        return Path(raw)
    return default_library()


def project_name() -> str:
    named = os.environ.get("LORE_PROJECT_NAME", "").strip()
    if named:
        return named
    return workspace_root().name or "this project"


def is_knowledge_store(directory: Path) -> bool:
    """True when this folder holds personas, not only a codebase-map status file.

    Mapping a repo that has no personas creates `.lore/graph-status.json`.
    That file must not hide the persona library.
    """
    lore = directory / ".lore"
    if not lore.is_dir():
        return False
    names = {entry.name for entry in lore.iterdir()}
    return names != {"graph-status.json"}


def find_project(start: Path) -> Path:
    """Return the directory that holds the persona store.

    A project folder wins. Otherwise the persona library is used, so an agent
    can call Lore from a project that does not keep its own personas.
    """
    current = _directory(start)
    for candidate in (current, *current.parents):
        if is_knowledge_store(candidate):
            return candidate
    library = library_root()
    if is_knowledge_store(library):
        return library.resolve()
    raise LoreNotFound(start)


def map_root(start: Path) -> Path:
    """Return the repository to map.

    `LORE_WORKSPACE` wins. Otherwise a project `.lore` store owns the map,
    walking up from `start` so a nested working directory still maps the repo.
    A repo with no persona store is mapped itself. The persona library is
    mapped only when the editor opened that library.
    """
    forced = os.environ.get("LORE_WORKSPACE", "").strip()
    if forced:
        return Path(forced).expanduser().resolve()
    current = _directory(start)
    library = library_root().expanduser().resolve()
    for candidate in (current, *current.parents):
        if candidate == library:
            return library
        if is_knowledge_store(candidate):
            return candidate
        if candidate.parent == candidate:
            break
    return current


def _directory(start: Path) -> Path:
    current = start.expanduser().resolve()
    if current.is_file():
        return current.parent
    return current

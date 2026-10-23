"""Create the `.lore` folder the setup site and the agent both use."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from lore.core.okf import read_doc


def pack_root() -> Path:
    raw = os.environ.get("LORE_PACK", "")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "examples" / "persona-pack"


def init_workspace(project: Path) -> Path:
    lore = project / ".lore"
    lore.mkdir(parents=True, exist_ok=True)
    (lore / "personas").mkdir(exist_ok=True)
    (lore / "skills").mkdir(exist_ok=True)
    (lore / "decisions").mkdir(exist_ok=True)
    config = lore / "lore.config.yaml"
    if not config.exists():
        config.write_text("token_budget: 800\nmax_items: 8\n", encoding="utf-8")
    return project


def copy_example(project: Path) -> None:
    init_workspace(project)
    pack = pack_root() / ".lore"
    for name in ("personas", "skills"):
        source = pack / name
        dest = project / ".lore" / name
        if not source.is_dir():
            continue
        if source.resolve() == dest.resolve():
            continue
        shutil.copytree(source, dest, dirs_exist_ok=True)


def ready_personas() -> list[dict[str, str]]:
    """Stable personas shipped with Lore, ready to copy into a library."""
    folder = pack_root() / ".lore" / "personas"
    rows: list[dict[str, str]] = []
    if not folder.is_dir():
        return rows
    for path in sorted(folder.glob("*.md")):
        doc = read_doc(path)
        if doc.get("status") != "stable":
            continue
        rows.append(
            {
                "id": path.stem,
                "title": doc.get("title") or path.stem,
                "summary": doc.get("summary"),
            }
        )
    return rows


def copy_persona(project: Path, slug: str) -> str:
    """Copy one ready-made persona and its skills. Draft fixtures are refused."""
    init_workspace(project)
    pack = pack_root() / ".lore"
    source = pack / "personas" / f"{slug}.md"
    if not source.is_file():
        raise FileNotFoundError(slug)
    doc = read_doc(source)
    if doc.get("status") != "stable":
        raise ValueError("That persona is not a starter.")
    dest = project / ".lore" / "personas" / source.name
    if source.resolve() != dest.resolve():
        dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    skills_src = pack / "skills" / slug
    skills_dest = project / ".lore" / "skills" / slug
    if skills_src.is_dir() and skills_src.resolve() != skills_dest.resolve():
        shutil.copytree(skills_src, skills_dest, dirs_exist_ok=True)
    return doc.get("id")

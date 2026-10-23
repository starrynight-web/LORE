"""Personas and the skills filed under them."""

from __future__ import annotations

from pathlib import Path

from lore.core.okf import Doc, read_doc, write_doc


def persona_id(name: str) -> str:
    if name.startswith("persona:"):
        return name
    return f"persona:{name}"


def persona_slug(name: str) -> str:
    return persona_id(name).split(":", 1)[1]


def lore_dir(project: Path) -> Path:
    return project / ".lore"


def list_personas(project: Path) -> list[Doc]:
    folder = lore_dir(project) / "personas"
    if not folder.is_dir():
        return []
    return [read_doc(path) for path in sorted(folder.glob("*.md"))]


def find_persona(project: Path, name: str) -> Doc | None:
    wanted = persona_id(name)
    slug = persona_slug(name)
    for doc in list_personas(project):
        if doc.get("id") == wanted:
            return doc
    direct = lore_dir(project) / "personas" / f"{slug}.md"
    if direct.is_file():
        return read_doc(direct)
    return None


def skill_belongs(path: Path, doc: Doc, name: str) -> bool:
    """True when the file is in this persona's folder and the header agrees."""
    slug = persona_slug(name)
    wanted = persona_id(name)
    if path.parent.name != slug:
        return False
    header_persona = doc.get("persona")
    return header_persona in {wanted, slug}


def is_served(path: Path, doc: Doc, name: str) -> bool:
    return skill_belongs(path, doc, name) and doc.get("status") == "stable"


def list_skill_files(project: Path) -> list[tuple[Path, Doc]]:
    root = lore_dir(project) / "skills"
    if not root.is_dir():
        return []
    return [(path, read_doc(path)) for path in sorted(root.rglob("*.md"))]


def served_skills(project: Path, name: str) -> list[Doc]:
    return [doc for path, doc in list_skill_files(project) if is_served(path, doc, name)]


def find_skill(project: Path, skill_name: str, persona: str | None = None) -> Doc | None:
    needle = skill_name.removeprefix("skill:")
    for path, doc in list_skill_files(project):
        ident = doc.get("id").removeprefix("skill:")
        title = doc.get("title")
        tail = ident.split("/")[-1]
        names = {ident, doc.get("id"), path.stem, path.stem.split("@", 1)[0], title, tail, tail.split("@", 1)[0]}
        if needle not in names:
            continue
        if persona is not None and not skill_belongs(path, doc, persona):
            return None
        if doc.get("status") != "stable":
            return None
        return doc
    return None


def file_slug(name: str) -> str:
    raw = persona_slug(name) if name.startswith("persona:") else name
    chars = [ch.lower() if ch.isalnum() else "-" for ch in raw.strip()]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "item"


def write_persona(
    project: Path,
    name: str,
    summary: str,
    body: str,
    *,
    title: str = "",
    status: str = "draft",
) -> Doc:
    slug = file_slug(name)
    ident = persona_id(slug)
    doc = Doc(
        header={
            "type": "persona",
            "id": ident,
            "title": title or name.strip() or slug,
            "status": status,
            "summary": summary,
            "skill_ids": [],
        },
        body=body if body.endswith("\n") else body + "\n",
    )
    path = lore_dir(project) / "personas" / f"{slug}.md"
    write_doc(path, doc)
    doc.path = path
    return doc


def write_skill(
    project: Path,
    persona: str,
    filename: str,
    *,
    title: str,
    summary: str,
    body: str,
    status: str = "draft",
) -> Doc:
    slug = persona_slug(persona)
    stem = filename.removesuffix(".md")
    if "@" not in stem:
        stem = f"{stem}@v1"
    skill = f"skill:{slug}/{stem}"
    doc = Doc(
        header={
            "type": "skill",
            "id": skill,
            "title": title or stem.split("@", 1)[0],
            "persona": persona_id(persona),
            "status": status,
            "summary": summary,
        },
        body=body,
    )
    path = lore_dir(project) / "skills" / slug / f"{stem}.md"
    write_doc(path, doc)
    doc.path = path
    _attach_skill(project, persona, skill)
    return doc


def set_status(project: Path, item_id: str, status: str) -> Doc:
    doc = _find_any(project, item_id)
    if doc is None or doc.path is None:
        raise FileNotFoundError(item_id)
    doc.header["status"] = status
    write_doc(doc.path, doc)
    return doc


def _attach_skill(project: Path, persona: str, skill: str) -> None:
    doc = find_persona(project, persona)
    if doc is None or doc.path is None:
        return
    current = doc.header.get("skill_ids")
    ids = [str(item) for item in current] if isinstance(current, list) else []
    if skill not in ids:
        ids.append(skill)
    doc.header["skill_ids"] = ids
    write_doc(doc.path, doc)


def _find_any(project: Path, item_id: str) -> Doc | None:
    wanted = item_id
    for doc in list_personas(project):
        if doc.get("id") == wanted or persona_slug(doc.get("id")) == item_id:
            return doc
    for _path, doc in list_skill_files(project):
        if doc.get("id") == wanted or doc.get("id").removeprefix("skill:") == item_id:
            return doc
    return None

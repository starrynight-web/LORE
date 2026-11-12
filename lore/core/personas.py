"""Personas and the skills filed under them."""

from __future__ import annotations

from pathlib import Path

from lore.core.okf import Doc, read_doc, write_doc


def persona_id(name: str) -> str:
    return f"persona:{persona_slug(name)}"


def persona_slug(name: str) -> str:
    """Fold spaces and capitals so "frontend engineer" is frontend-engineer."""
    raw = name.strip()
    if raw.startswith("persona:"):
        raw = raw.split(":", 1)[1]
    chars = [ch.lower() if ch.isalnum() else "-" for ch in raw.strip()]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "item"


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


def visible_skills(project: Path) -> list[tuple[Path, Doc]]:
    """Skills whose folder and header name the same role.

    A file that sits in one role's folder but names another role is a mismatch.
    The agent already ignores it. The website should too.
    """
    return [(path, doc) for path, doc in list_skill_files(project) if skill_belongs(path, doc, path.parent.name)]


def served_skills(project: Path, name: str) -> list[Doc]:
    return [doc for path, doc in list_skill_files(project) if is_served(path, doc, name)]


def _servable(project: Path, path: Path, doc: Doc, persona: str | None) -> bool:
    """A stable skill only ships when its owning persona is stable too."""
    if doc.get("status") != "stable":
        return False
    owner_name = persona if persona is not None else path.parent.name
    if not skill_belongs(path, doc, owner_name):
        return False
    owner = find_persona(project, owner_name)
    return owner is not None and owner.get("status") == "stable"


def find_skill(project: Path, skill_name: str, persona: str | None = None) -> Doc | None:
    needle = skill_name.removeprefix("skill:")
    exact: list[tuple[Path, Doc]] = []
    loose: list[tuple[Path, Doc]] = []
    for path, doc in list_skill_files(project):
        full = str(doc.get("id") or "")
        ident = full.removeprefix("skill:")
        tail = ident.split("/")[-1]
        if needle in {full, ident}:
            exact.append((path, doc))
            continue
        names = {path.stem, path.stem.split("@", 1)[0], doc.get("title"), tail, tail.split("@", 1)[0]}
        if needle in names:
            loose.append((path, doc))
    if exact:
        for path, doc in exact:
            if _servable(project, path, doc, persona):
                return doc
        return None
    matches = [
        (path, doc) for path, doc in loose if _servable(project, path, doc, persona)
    ]
    ids = {str(doc.get("id")) for _path, doc in matches}
    if len(ids) > 1:
        raise ValueError(
            f"{skill_name} is ambiguous; use a full skill id: " + ", ".join(sorted(ids))
        )
    if matches:
        return matches[0][1]
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
    try:
        from lore.core.governance import stamp_scan

        return stamp_scan(doc, use_skillspector=False)
    except Exception:  # noqa: BLE001 - draft write must not fail on scan errors
        return doc


def locate_skill(project: Path, skill_name: str) -> tuple[Path, Doc] | None:
    """Find a skill file even when it is still a draft."""
    needle = skill_name.removeprefix("skill:")
    for path, doc in list_skill_files(project):
        ident = doc.get("id").removeprefix("skill:")
        tail = ident.split("/")[-1]
        names = {
            ident,
            doc.get("id"),
            path.stem,
            path.stem.split("@", 1)[0],
            doc.get("title"),
            tail,
            tail.split("@", 1)[0],
            skill_name,
        }
        if needle in names or skill_name in names:
            return path, doc
    return None


def update_persona(
    project: Path,
    name: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    body: str | None = None,
    status: str | None = None,
) -> Doc:
    doc = find_persona(project, name)
    if doc is None or doc.path is None:
        raise FileNotFoundError(name)
    before = (doc.get("title"), doc.get("summary"), doc.body)
    if title is not None:
        text = title.strip()
        if not text:
            raise ValueError("A persona needs a title.")
        doc.header["title"] = text
    if summary is not None:
        doc.header["summary"] = summary.strip()
    if body is not None:
        doc.body = body
    promote = False
    if status is not None:
        if status not in {"draft", "stable"}:
            raise ValueError("Status must be draft or stable.")
        promote = status == "stable"
    content_changed = (doc.get("title"), doc.get("summary"), doc.body) != before
    if content_changed or status is not None:
        doc.header["status"] = "draft"
    if content_changed:
        doc.header.pop("governance", None)
    write_doc(doc.path, doc)
    if content_changed:
        try:
            from lore.core.governance import stamp_scan

            doc = stamp_scan(doc, use_skillspector=False)
        except Exception:  # noqa: BLE001, S110 - draft write must not fail on scan errors
            pass
    if promote:
        from lore.core.governance import approve_item

        return approve_item(project, doc.get("id"))
    return doc


def delete_persona(project: Path, name: str) -> None:
    doc = find_persona(project, name)
    if doc is None or doc.path is None:
        raise FileNotFoundError(name)
    doc.path.unlink()


def update_skill(
    project: Path,
    skill_name: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    body: str | None = None,
    status: str | None = None,
) -> Doc:
    found = locate_skill(project, skill_name)
    if found is None:
        raise FileNotFoundError(skill_name)
    path, doc = found
    before = (doc.get("title"), doc.get("summary"), doc.body)
    if title is not None:
        text = title.strip()
        if not text:
            raise ValueError("A skill needs a title.")
        doc.header["title"] = text
    if summary is not None:
        doc.header["summary"] = summary.strip()
    if body is not None:
        doc.body = body
    promote = False
    if status is not None:
        if status not in {"draft", "stable"}:
            raise ValueError("Status must be draft or stable.")
        promote = status == "stable"
    content_changed = (doc.get("title"), doc.get("summary"), doc.body) != before
    if content_changed or status is not None:
        doc.header["status"] = "draft"
    if content_changed:
        doc.header.pop("governance", None)
    write_doc(path, doc)
    doc.path = path
    if content_changed:
        try:
            from lore.core.governance import stamp_scan

            doc = stamp_scan(doc, use_skillspector=False)
        except Exception:  # noqa: BLE001, S110 - draft write must not fail on scan errors
            pass
    if promote:
        from lore.core.governance import approve_item

        return approve_item(project, doc.get("id"))
    return doc


def delete_skill(project: Path, skill_name: str) -> None:
    found = locate_skill(project, skill_name)
    if found is None:
        raise FileNotFoundError(skill_name)
    path, doc = found
    ident = doc.get("id")
    path.unlink()
    for persona in list_personas(project):
        current = persona.header.get("skill_ids")
        if not isinstance(current, list) or persona.path is None:
            continue
        kept = [item for item in current if str(item) != ident]
        if kept != current:
            persona.header["skill_ids"] = kept
            write_doc(persona.path, persona)


def find_any(project: Path, item_id: str) -> Doc | None:
    """Locate a persona or skill by id (draft or stable)."""
    wanted = item_id
    for doc in list_personas(project):
        if doc.get("id") == wanted or persona_slug(doc.get("id")) == item_id:
            return doc
    for _path, doc in list_skill_files(project):
        if doc.get("id") == wanted or doc.get("id").removeprefix("skill:") == item_id:
            return doc
    return None


def set_status(project: Path, item_id: str, status: str) -> Doc:
    """Set status. Promoting to stable runs governance approve."""
    if status == "stable":
        from lore.core.governance import approve_item

        return approve_item(project, item_id)
    doc = find_any(project, item_id)
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

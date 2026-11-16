"""Skills waiting for a persona.

A skill can come from a file the person already has, or from a skills.sh
result. It stays here until a persona is saved, then it is filed under that
persona.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml

from lore.core.okf import Doc, read_doc, write_doc
from lore.core.personas import (
    file_slug,
    find_persona,
    list_skill_files,
    lore_dir,
    persona_slug,
    skill_belongs,
    write_skill,
)

_MAX_BYTES = 200_000
_MAX_FOLDER_SKILLS = 50
_FOLDER_DEPTH = 2
Opener = Callable[..., Any]


def inbox_dir(project: Path) -> Path:
    return project / ".lore" / "inbox"


def list_inbox(project: Path) -> list[dict[str, str]]:
    recover_orphaned_skills(project)
    folder = inbox_dir(project)
    if not folder.is_dir():
        return []
    rows = []
    for path in sorted(folder.glob("*.md")):
        doc = read_doc(path)
        title = doc.get("title") or path.stem
        summary = doc.get("summary")
        source = doc.get("source")
        if not summary.strip():
            repaired = _repair_summary(doc)
            if repaired is not None:
                title, summary, doc = repaired
                write_doc(path, doc)
        rows.append(
            {
                "id": path.stem,
                "title": title,
                "summary": summary,
                "source": source,
            }
        )
    return rows


def park_skill_in_inbox(project: Path, doc: Doc) -> dict[str, str]:
    """Put a filed skill back into waiting. Body and summary are kept; approval is cleared."""
    title = str(doc.get("title") or "").strip() or "skill"
    summary = str(doc.get("summary") or "").strip()
    source = str(doc.get("source") or "").strip()
    body = doc.body if doc.body.endswith("\n") else doc.body + "\n"
    slug = _unique_inbox_slug(project, title)
    parked = Doc(
        header={
            "type": "skill",
            "id": f"inbox:{slug}",
            "title": title,
            "summary": summary,
            "status": "draft",
            "source": source,
        },
        body=body if body.strip() else f"{title}\n",
    )
    path = inbox_dir(project) / f"{slug}.md"
    write_doc(path, parked)
    return {"id": slug, "title": title, "summary": summary, "source": source}


def return_persona_skills_to_inbox(project: Path, persona: str) -> list[dict[str, str]]:
    """Move every skill filed under this persona into waiting, then remove the filed copies."""
    slug = persona_slug(persona)
    parked: list[dict[str, str]] = []
    folder = lore_dir(project) / "skills" / slug
    for path, doc in list(list_skill_files(project)):
        if not skill_belongs(path, doc, persona):
            continue
        parked.append(park_skill_in_inbox(project, doc))
        path.unlink(missing_ok=True)
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    return parked


def recover_orphaned_skills(project: Path) -> list[dict[str, str]]:
    """Skills whose persona file is gone go back to waiting so they can be reselected."""
    parked: list[dict[str, str]] = []
    for path, doc in list(list_skill_files(project)):
        owner = path.parent.name
        if find_persona(project, owner) is not None:
            continue
        if not skill_belongs(path, doc, owner):
            continue
        parked.append(park_skill_in_inbox(project, doc))
        path.unlink(missing_ok=True)
        folder = path.parent
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    return parked


def _unique_inbox_slug(project: Path, title: str) -> str:
    base = file_slug(title)
    slug = base
    folder = inbox_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    index = 2
    while (folder / f"{slug}.md").is_file():
        slug = f"{base}-{index}"
        index += 1
    return slug


def add_text(project: Path, name: str, content: str, source: str = "") -> dict[str, str]:
    if len(content.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("That skill file is too large.")
    title, summary, body = _skill_meta(content, name)
    if not title:
        raise ValueError("A skill needs a name.")
    slug = file_slug(title)
    doc = Doc(
        header={
            "type": "skill",
            "id": f"inbox:{slug}",
            "title": title,
            "summary": summary,
            "status": "draft",
            "source": source,
        },
        body=body if body.strip() else content.strip() + "\n",
    )
    path = inbox_dir(project) / f"{slug}.md"
    write_doc(path, doc)
    return {"id": slug, "title": title, "summary": summary, "source": source}


def remove_inbox(project: Path, skill_id: str) -> None:
    slug = file_slug(skill_id)
    path = inbox_dir(project) / f"{slug}.md"
    if not path.is_file():
        raise FileNotFoundError(skill_id)
    path.unlink()


def discover_skill_files(root: Path, *, max_depth: int = _FOLDER_DEPTH) -> list[Path]:
    """Find SKILL.md files under a skills.sh-style folder tree."""
    base = root.expanduser().resolve()
    if not base.is_dir():
        raise ValueError("That path is not a folder.")
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file() or resolved.is_symlink():
            return
        try:
            resolved.relative_to(base)
        except ValueError:
            return
        seen.add(resolved)
        found.append(resolved)

    direct = base / "SKILL.md"
    if direct.is_file():
        add(direct)
        return found

    for depth in range(1, max_depth + 1):
        pattern = "/".join(["*"] * depth) + "/SKILL.md"
        for path in sorted(base.glob(pattern)):
            add(path)
            if len(found) >= _MAX_FOLDER_SKILLS:
                return found
    if not found:
        for path in sorted(base.glob("*.md")):
            add(path)
            if len(found) >= _MAX_FOLDER_SKILLS:
                break
    return found


def add_from_folder(project: Path, folder: Path) -> list[dict[str, str]]:
    """Import every discovered skill under `folder` into the inbox."""
    files = discover_skill_files(Path(folder))
    if not files:
        raise ValueError(
            "No skill files were found. Choose a folder that contains SKILL.md "
            "(or a parent of several skill folders)."
        )
    saved: list[dict[str, str]] = []
    errors: list[str] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            errors.append(path.name)
            continue
        label = path.parent.name if path.name.lower() == "skill.md" else path.name
        try:
            row = add_text(
                project,
                label,
                content,
                source=f"local:{path.parent.name}",
            )
        except ValueError:
            errors.append(path.name)
            continue
        saved.append(row)
    if not saved:
        raise ValueError(
            "Those folders could not be read as skills"
            + (f" ({', '.join(errors[:3])})" if errors else ".")
        )
    return saved


def adopt_inbox(project: Path, persona: str, only: list[str] | None = None) -> list[str]:
    """File waiting skills under the persona, then remove them from the inbox.

    `only` limits the move to those inbox ids. `None` files every waiting skill.
    """
    wanted = None if only is None else {file_slug(item) for item in only}
    saved: list[str] = []
    for row in list_inbox(project):
        if wanted is not None and row["id"] not in wanted:
            continue
        path = inbox_dir(project) / f"{row['id']}.md"
        doc = read_doc(path)
        written = write_skill(
            project,
            persona,
            row["id"],
            title=doc.get("title") or row["id"],
            summary=doc.get("summary"),
            body=doc.body,
            status="draft",
        )
        path.unlink()
        saved.append(written.get("id"))
    return saved


def featured_registry(opener: Opener | None = None) -> list[dict[str, str | int]]:
    """A first screen of skills from skills.sh, ordered by installs."""
    return search_registry("skill", opener, limit=24)


def search_registry(
    query: str,
    opener: Opener | None = None,
    *,
    limit: int = 8,
) -> list[dict[str, str | int]]:
    text = query.strip()
    if len(text) < 2:
        raise ValueError("Type at least two characters to search.")
    bounded = min(max(limit, 1), 200)
    url = "https://skills.sh/api/search?" + urllib.parse.urlencode({"q": text, "limit": str(bounded)})
    loaded = _get_json(url, opener or urllib.request.urlopen)
    skills = loaded.get("skills")
    if not isinstance(skills, list):
        return []
    rows: list[dict[str, str | int]] = []
    for item in skills:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", ""))
        skill_id = str(item.get("skillId") or item.get("slug") or "")
        if not _safe_source(source) or not _safe_id(skill_id):
            continue
        installs = item.get("installs", 0)
        rows.append(
            {
                "name": str(item.get("name") or skill_id),
                "skill_id": skill_id,
                "source": source,
                "installs": int(installs) if isinstance(installs, int) else 0,
            }
        )
    rows.sort(key=lambda row: int(row["installs"]), reverse=True)
    return rows


def add_from_registry(
    project: Path,
    source: str,
    skill_id: str,
    opener: Opener | None = None,
) -> dict[str, str]:
    if not _safe_source(source) or not _safe_id(skill_id):
        raise ValueError("That skill is not from skills.sh.")
    text = _fetch_skill(source, skill_id, opener or urllib.request.urlopen)
    return add_text(project, skill_id, text, source=f"skills.sh:{source}/{skill_id}")


def _fetch_skill(source: str, skill_id: str, opener: Opener) -> str:
    for rel in _skill_paths(source, skill_id, opener):
        for branch in ("main", "master"):
            url = f"https://raw.githubusercontent.com/{source}/{branch}/{rel}"
            try:
                body = _get_text(url, opener)
            except ValueError:
                continue
            if body.lstrip().startswith("<!") or len(body.strip()) < 20:
                continue
            return body
    page = _registry_page(source, skill_id, opener)
    if page:
        return page
    raise ValueError("That skill could not be downloaded. Try it again in a moment.")


def _skill_paths(source: str, skill_id: str, opener: Opener) -> list[str]:
    names = [skill_id]
    parts = skill_id.split("-")
    for index in range(1, len(parts)):
        names.append("-".join(parts[index:]))
    guessed = [f"{name}/SKILL.md" for name in names]
    guessed += [f"skills/{name}/SKILL.md" for name in names]
    guessed += [f".agents/skills/{name}/SKILL.md" for name in names]
    found = _tree_paths(source, names, opener)
    ordered: list[str] = []
    for path in found + guessed:
        if path not in ordered:
            ordered.append(path)
    return ordered


def _tree_paths(source: str, names: list[str], opener: Opener) -> list[str]:
    url = f"https://api.github.com/repos/{source}/git/trees/HEAD?recursive=1"
    try:
        loaded = _get_json(url, opener)
    except ValueError:
        return []
    tree = loaded.get("tree")
    if not isinstance(tree, list):
        return []
    files: list[str] = []
    for item in tree:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        if path.endswith("/SKILL.md") or path == "SKILL.md":
            files.append(path)
    ranked = [path for path in files if any(name in path for name in names)]
    ranked.sort(key=len)
    return ranked[:4]


def _get_json(url: str, opener: Opener) -> dict[str, Any]:
    raw = _get_text(url, opener)
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("skills.sh returned an unreadable answer.") from exc
    if not isinstance(loaded, dict):
        raise ValueError("skills.sh returned an unreadable answer.")  # noqa: TRY004
    return loaded


class _Prose(HTMLParser):
    """Pull the readable skill text out of a skills.sh page."""

    def __init__(self) -> None:
        super().__init__()
        self._depth = 0
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class") or ""
        if tag == "div" and self._depth == 0 and "prose" in classes.split():
            self._depth = 1
            return
        if self._depth == 0:
            return
        if tag == "div":
            self._depth += 1
        if tag in {"h1", "h2", "h3", "p", "li"}:
            self.parts.append("\n")
        if tag in {"script", "style"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if self._skip and tag in {"script", "style"}:
            self._skip -= 1
            return
        if self._depth and tag == "div":
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._depth and not self._skip:
            self.parts.append(data)


def _registry_page(source: str, skill_id: str, opener: Opener) -> str:
    """Last resort when the skill file is not at a guessed GitHub path."""
    url = f"https://skills.sh/{source}/{skill_id}"
    try:
        html = _get_text(url, opener)
    except ValueError:
        return ""
    parser = _Prose()
    parser.feed(html)
    text = " ".join("".join(parser.parts).split())
    if len(text) < 40:
        return ""
    title = skill_id.replace("-", " ")
    return f"---\nname: {title}\ndescription: {text[:240]}\n---\n{text}\n"


def _get_text(url: str, opener: Opener) -> str:
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in {"skills.sh", "www.skills.sh", "raw.githubusercontent.com", "api.github.com"}:
        raise ValueError("That address is not a skill registry.")
    request = urllib.request.Request(url, headers={"User-Agent": "Lore"})
    try:
        with opener(request, timeout=20) as response:
            final = getattr(response, "geturl", lambda: url)()
            final_host = urllib.parse.urlparse(str(final)).hostname or ""
            if final_host not in {
                "skills.sh",
                "www.skills.sh",
                "raw.githubusercontent.com",
                "api.github.com",
            }:
                raise ValueError("That address is not a skill registry.")
            raw = response.read(_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError("skills.sh did not return that skill.") from exc
    except ValueError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("skills.sh could not be reached.") from exc
    data = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
    if len(data) > _MAX_BYTES:
        raise ValueError("That skill file is too large.")
    return data.decode("utf-8", errors="replace")


def _skill_meta(content: str, fallback_name: str) -> tuple[str, str, str]:
    """Title, summary, and body for a skill file (handles nested / messy frontmatter)."""
    header, body = _split(content)
    title = str(header.get("title") or header.get("name") or fallback_name).strip()
    summary = str(header.get("summary") or header.get("description") or "").strip()
    # skills.sh files often leave the original SKILL.md frontmatter in the body
    # when YAML rejected unquoted colons in description on the first pass.
    if (not summary or title == fallback_name) and body.lstrip().startswith("---"):
        nested, nested_body = _split(body.lstrip())
        if nested:
            if not summary:
                summary = str(
                    nested.get("summary") or nested.get("description") or ""
                ).strip()
            nested_title = str(nested.get("title") or nested.get("name") or "").strip()
            if nested_title and (not title or title == fallback_name):
                title = nested_title
            if nested_body.strip():
                body = nested_body
    if not summary:
        summary = _first_sentence(body)
    return title, summary, body


def _repair_summary(doc: Doc) -> tuple[str, str, Doc] | None:
    """Fill an empty inbox summary from nested frontmatter or the first sentence."""
    if doc.get("summary").strip():
        return None
    fallback = doc.get("title") or "skill"
    title, summary, body = _skill_meta(doc.body, fallback)
    if not summary.strip():
        return None
    header = dict(doc.header)
    if title and title != fallback:
        header["title"] = title
    header["summary"] = summary.strip()
    return str(header.get("title") or fallback), summary.strip(), Doc(
        header=header, body=body if body.strip() else doc.body, path=doc.path
    )


def _first_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    for sep in (". ", "? ", "! "):
        index = cleaned.find(sep)
        if index > 40:
            return cleaned[: index + 1][:280]
    return cleaned[:240]


def _split(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    rest = text[3:].removeprefix("\n")
    marker = "\n---"
    end = rest.find(marker)
    if end < 0:
        return {}, text
    raw_header = rest[:end]
    body = rest[end + len(marker) :].removeprefix("\n")
    try:
        loaded = yaml.safe_load(raw_header)
    except yaml.YAMLError:
        return _split_loose(raw_header), body
    if isinstance(loaded, dict):
        return dict(loaded), body
    return _split_loose(raw_header), body


def _split_loose(raw: str) -> dict[str, Any]:
    """Line-based fallback when YAML rejects unquoted colons in description values."""
    header: dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if not key or any(ch.isspace() for ch in key):
            continue
        if key in header:
            continue
        header[key] = value.strip().strip("\"'")
    return header


def _safe_source(source: str) -> bool:
    parts = source.split("/")
    if len(parts) != 2:
        return False
    return all(_safe_id(part) for part in parts)


def _safe_id(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    return all(ch.isalnum() or ch in "._-" for ch in value)

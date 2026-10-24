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
from lore.core.personas import file_slug, write_skill

_MAX_BYTES = 200_000
Opener = Callable[..., Any]


def inbox_dir(project: Path) -> Path:
    return project / ".lore" / "inbox"


def list_inbox(project: Path) -> list[dict[str, str]]:
    folder = inbox_dir(project)
    if not folder.is_dir():
        return []
    rows = []
    for path in sorted(folder.glob("*.md")):
        doc = read_doc(path)
        rows.append(
            {
                "id": path.stem,
                "title": doc.get("title") or path.stem,
                "summary": doc.get("summary"),
                "source": doc.get("source"),
            }
        )
    return rows


def add_text(project: Path, name: str, content: str, source: str = "") -> dict[str, str]:
    if len(content.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("That skill file is too large.")
    header, body = _split(content)
    title = str(header.get("title") or header.get("name") or name).strip()
    summary = str(header.get("summary") or header.get("description") or "").strip()
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


def _split(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    rest = text[3:].removeprefix("\n")
    marker = "\n---"
    end = rest.find(marker)
    if end < 0:
        return {}, text
    try:
        loaded = yaml.safe_load(rest[:end])
    except yaml.YAMLError:
        return {}, text
    header = loaded if isinstance(loaded, dict) else {}
    return header, rest[end + len(marker) :].removeprefix("\n")


def _safe_source(source: str) -> bool:
    parts = source.split("/")
    if len(parts) != 2:
        return False
    return all(_safe_id(part) for part in parts)


def _safe_id(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    return all(ch.isalnum() or ch in "._-" for ch in value)

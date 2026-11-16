"""Skills wait in the inbox, then move under a persona."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Self

import pytest
from lore.core.inbox import (
    add_from_folder,
    add_from_registry,
    add_text,
    adopt_inbox,
    discover_skill_files,
    list_inbox,
    recover_orphaned_skills,
    search_registry,
)
from lore.core.personas import (
    delete_persona,
    find_persona,
    locate_skill,
    write_persona,
    write_skill,
)
from lore.core.workspace import init_workspace


class _Body:
    def __init__(self, payload: bytes, url: str) -> None:
        self.payload = payload
        self.url = url

    def read(self, _limit: int = -1) -> bytes:
        return self.payload

    def geturl(self) -> str:
        return self.url

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_a_file_waits_until_a_persona_adopts_it(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    content = "---\nname: Widget shape\ndescription: Prefer round widgets.\n---\nKeep the widget round.\n"
    added = add_text(tmp_path, "ignored.md", content)
    assert added["title"] == "Widget shape"
    assert added["summary"] == "Prefer round widgets."
    write_persona(tmp_path, "Widget maker", "Makes widgets.", "You make widgets.\n")
    ids = adopt_inbox(tmp_path, "persona:widget-maker")
    assert ids == ["skill:widget-maker/widget-shape@v1"]
    persona = find_persona(tmp_path, "widget-maker")
    assert persona is not None
    assert persona.header["skill_ids"] == ["skill:widget-maker/widget-shape@v1"]
    assert not (tmp_path / ".lore" / "inbox" / "widget-shape.md").exists()


def test_deleting_a_persona_returns_its_skills_to_waiting(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    add_text(
        tmp_path,
        "shape.md",
        "---\nname: Widget shape\ndescription: Prefer round widgets.\n---\nKeep the widget round.\n",
    )
    add_text(
        tmp_path,
        "color.md",
        "---\nname: Widget color\ndescription: Prefer blue widgets.\n---\nKeep the widget blue.\n",
    )
    write_persona(tmp_path, "Widget maker", "Makes widgets.", "You make widgets.\n")
    adopt_inbox(tmp_path, "persona:widget-maker")
    assert list_inbox(tmp_path) == []
    delete_persona(tmp_path, "widget-maker")
    assert find_persona(tmp_path, "widget-maker") is None
    waiting = list_inbox(tmp_path)
    titles = sorted(row["title"] for row in waiting)
    assert titles == ["Widget color", "Widget shape"]
    assert locate_skill(tmp_path, "skill:widget-maker/widget-shape@v1") is None
    assert not (tmp_path / ".lore" / "skills" / "widget-maker").exists()


def test_orphaned_filed_skills_are_recovered_into_waiting(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_persona(tmp_path, "Widget maker", "Makes widgets.", "You make widgets.\n")
    write_skill(
        tmp_path,
        "persona:widget-maker",
        "shape",
        title="Widget shape",
        summary="Prefer round widgets.",
        body="Keep the widget round.\n",
        status="stable",
    )
    persona_path = tmp_path / ".lore" / "personas" / "widget-maker.md"
    persona_path.unlink()
    recovered = recover_orphaned_skills(tmp_path)
    assert [row["title"] for row in recovered] == ["Widget shape"]
    waiting = list_inbox(tmp_path)
    assert waiting[0]["title"] == "Widget shape"
    assert waiting[0]["summary"] == "Prefer round widgets."
    assert locate_skill(tmp_path, "skill:widget-maker/shape@v1") is None


def test_unquoted_colon_in_description_still_keeps_summary(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    content = (
        "---\n"
        "name: minimalist ui\n"
        "description: Enforces strict design constraints: no gradients, heavy shadows\n"
        "---\n"
        "Keep the page quiet.\n"
    )
    added = add_text(tmp_path, "minimalist-ui", content)
    assert added["title"] == "minimalist ui"
    assert "constraints" in added["summary"]
    assert "gradients" in added["summary"]


def test_list_inbox_repairs_empty_summary_from_nested_frontmatter(tmp_path: Path) -> None:
    from lore.core.inbox import list_inbox
    from lore.core.okf import Doc, write_doc

    init_workspace(tmp_path)
    path = tmp_path / ".lore" / "inbox" / "broken.md"
    write_doc(
        path,
        Doc(
            header={
                "type": "skill",
                "id": "inbox:broken",
                "title": "broken",
                "summary": "",
                "status": "draft",
                "source": "skills.sh:x/y",
            },
            body=(
                "---\n"
                "name: fixed title\n"
                "description: Enforces strict design constraints: no gradients\n"
                "---\n"
                "Body text.\n"
            ),
        ),
    )
    rows = list_inbox(tmp_path)
    assert len(rows) == 1
    assert rows[0]["title"] == "fixed title"
    assert "constraints" in rows[0]["summary"]
    # Repair is persisted.
    again = list_inbox(tmp_path)
    assert again[0]["summary"] == rows[0]["summary"]


def test_registry_search_and_add(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    def opener(request: object, timeout: int = 20) -> _Body:
        del timeout
        url = request.full_url  # type: ignore[attr-defined]
        if "skills.sh" in url:
            payload = {
                "skills": [
                    {
                        "name": "React practices",
                        "skillId": "react-practices",
                        "source": "vercel-labs/agent-skills",
                        "installs": 10,
                    },
                    {"name": "bad", "skillId": "../etc", "source": "https://evil.example", "installs": 1},
                ]
            }
            return _Body(json.dumps(payload).encode("utf-8"), url)
        text = "---\nname: React practices\ndescription: Use React.\n---\nPrefer function components.\n"
        return _Body(text.encode("utf-8"), url)

    found = search_registry("react", opener)
    assert len(found) == 1
    assert found[0]["skill_id"] == "react-practices"
    added = add_from_registry(tmp_path, "vercel-labs/agent-skills", "react-practices", opener)
    assert added["title"] == "React practices"
    assert (tmp_path / ".lore" / "inbox" / "react-practices.md").is_file()


def test_registry_reads_a_skill_from_its_shorter_folder(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    def opener(request: object, timeout: int = 20) -> _Body:
        del timeout
        url = str(request.full_url)  # type: ignore[attr-defined]
        if "git/trees" in url:
            payload = {"tree": [{"path": "skills/react-best-practices/SKILL.md"}]}
            return _Body(json.dumps(payload).encode("utf-8"), url)
        if url.endswith("skills/react-best-practices/SKILL.md"):
            text = "---\nname: React practices\ndescription: Use React.\n---\nPrefer function components.\n"
            return _Body(text.encode("utf-8"), url)
        raise ValueError("missing")

    added = add_from_registry(tmp_path, "vercel-labs/agent-skills", "vercel-react-best-practices", opener)
    assert added["title"] == "React practices"


def test_registry_uses_the_skills_page_when_the_file_is_not_on_github(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    def opener(request: object, timeout: int = 20) -> _Body:
        del timeout
        url = str(request.full_url)  # type: ignore[attr-defined]
        if url.startswith("https://skills.sh/vercel/ai/"):
            html = (
                '<div class="prose prose-invert"><p>'
                "Use the AI SDK generateText helper for every new feature in this app."
                "</p></div>"
            )
            return _Body(html.encode("utf-8"), url)
        raise ValueError("missing")

    added = add_from_registry(tmp_path, "vercel/ai", "ai-sdk", opener)
    assert added["title"] == "ai sdk"
    saved = (tmp_path / ".lore" / "inbox" / "ai-sdk.md").read_text(encoding="utf-8")
    assert "generateText" in saved


def test_registry_refuses_a_source_that_is_not_a_github_repo(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="skills.sh"):
        add_from_registry(tmp_path, "https://evil.example/x", "react", lambda *_args: None)


def test_discover_and_import_skill_folders(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    root = tmp_path / "skills"
    first = root / "round-widgets"
    second = root / "square-widgets"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "SKILL.md").write_text(
        "---\nname: Round widgets\ndescription: Prefer round.\n---\nKeep them round.\n",
        encoding="utf-8",
    )
    (second / "SKILL.md").write_text(
        "---\nname: Square widgets\ndescription: Prefer square.\n---\nKeep them square.\n",
        encoding="utf-8",
    )
    found = discover_skill_files(root)
    assert len(found) == 2
    saved = add_from_folder(tmp_path, root)
    assert {row["title"] for row in saved} == {"Round widgets", "Square widgets"}
    assert (tmp_path / ".lore" / "inbox" / "round-widgets.md").is_file()
    assert (tmp_path / ".lore" / "inbox" / "square-widgets.md").is_file()


def test_import_single_skill_folder(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    folder = tmp_path / "ai-video-generation"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: AI video\ndescription: Make clips.\n---\nUse Veo.\n",
        encoding="utf-8",
    )
    saved = add_from_folder(tmp_path, folder)
    assert len(saved) == 1
    assert saved[0]["title"] == "AI video"

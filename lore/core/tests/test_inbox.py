"""Skills wait in the inbox, then move under a persona."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Self

import pytest
from lore.core.inbox import add_from_registry, add_text, adopt_inbox, search_registry
from lore.core.personas import find_persona, write_persona
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
    write_persona(tmp_path, "Widget maker", "Makes widgets.", "You make widgets.\n")
    ids = adopt_inbox(tmp_path, "persona:widget-maker")
    assert ids == ["skill:widget-maker/widget-shape@v1"]
    persona = find_persona(tmp_path, "widget-maker")
    assert persona is not None
    assert persona.header["skill_ids"] == ["skill:widget-maker/widget-shape@v1"]
    assert not (tmp_path / ".lore" / "inbox" / "widget-shape.md").exists()


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


def test_registry_refuses_a_source_that_is_not_a_github_repo(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="skills.sh"):
        add_from_registry(tmp_path, "https://evil.example/x", "react", lambda *_args: None)

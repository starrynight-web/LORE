from __future__ import annotations

from pathlib import Path

import pytest
from lore.core.okf import Doc, read_doc, write_doc
from lore.core.paths import LoreNotFound, default_library, find_project, library_root
from lore.core.personas import served_skills
from lore.core.tests.pack import PACK


def test_copy_example_onto_its_own_pack_leaves_the_files() -> None:
    from lore.core.workspace import copy_example, pack_root

    persona = pack_root() / ".lore" / "personas" / "frontend-engineer.md"
    before = persona.read_text(encoding="utf-8")
    copy_example(pack_root())
    assert persona.read_text(encoding="utf-8") == before


def test_round_trip_keeps_unknown_header_keys(tmp_path: Path) -> None:
    source = PACK / ".lore" / "personas" / "frontend-engineer.md"
    doc = read_doc(source)
    doc.header["custom_note"] = "kept"
    dest = tmp_path / "again.md"
    write_doc(dest, doc)
    again = read_doc(dest)
    assert again.header["custom_note"] == "kept"
    assert again.header["id"] == doc.header["id"]
    assert again.body == doc.body


def test_write_then_read_preserves_body(tmp_path: Path) -> None:
    doc = Doc(header={"type": "persona", "id": "persona:sample", "extra": 1}, body="line one\nline two\n")
    path = tmp_path / "sample.md"
    write_doc(path, doc)
    again = read_doc(path)
    assert again.header["extra"] == 1
    assert again.body == "line one\nline two\n"


def test_frontend_skills_are_only_its_stable_ones() -> None:
    skills = served_skills(PACK, "frontend-engineer")
    ids = [doc.get("id") for doc in skills]
    assert ids == [
        "skill:frontend-engineer/react-practices@v1",
        "skill:frontend-engineer/tailwind-rules@v1",
        "skill:frontend-engineer/ui-ux-pro-max@v1",
    ]
    assert "skill:backend-engineer/sql-migrations@v1" not in ids


def test_mismatched_persona_field_is_not_served() -> None:
    ids = [doc.get("id") for doc in served_skills(PACK, "frontend-engineer")]
    assert "skill:frontend-engineer/wrong-owner@v1" not in ids


def test_mismatched_skill_is_hidden_from_the_website_list() -> None:
    from lore.core.personas import visible_skills

    titles = [doc.get("title") for _path, doc in visible_skills(PACK)]
    assert "Wrong owner" not in titles
    assert "React practices" in titles


def test_library_paths_follow_the_operating_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LORE_LIBRARY", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    assert default_library("linux", tmp_path) == tmp_path / ".local" / "share" / "lore"
    assert default_library("Darwin", tmp_path) == tmp_path / "Library" / "Application Support" / "Lore"
    assert default_library("Windows", tmp_path) == tmp_path / "AppData" / "Roaming" / "Lore"
    monkeypatch.setenv("LORE_LIBRARY", str(tmp_path / "chosen"))
    assert library_root() == tmp_path / "chosen"


def test_missing_lore_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.core.paths.library_root", lambda: tmp_path / "absent")
    with pytest.raises(LoreNotFound, match="No .lore folder"):
        find_project(tmp_path)


def test_shared_library_is_used_when_the_project_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "Lore"
    (library / ".lore").mkdir(parents=True)
    monkeypatch.setattr("lore.core.paths.library_root", lambda: library)
    other = tmp_path / "app"
    other.mkdir()
    assert find_project(other) == library.resolve()


def test_a_project_folder_wins_over_the_shared_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "Lore"
    (library / ".lore").mkdir(parents=True)
    local = tmp_path / "app"
    (local / ".lore").mkdir(parents=True)
    monkeypatch.setattr("lore.core.paths.library_root", lambda: library)
    assert find_project(local) == local.resolve()


def test_ready_made_persona_copies_its_skills(tmp_path: Path) -> None:
    from lore.core.workspace import copy_persona, ready_personas

    rows = ready_personas()
    ids = {row["id"] for row in rows}
    assert "frontend-engineer" in ids
    assert "draft-persona" not in ids
    copy_persona(tmp_path, "frontend-engineer")
    persona = tmp_path / ".lore" / "personas" / "frontend-engineer.md"
    assert "status: stable" in persona.read_text(encoding="utf-8")
    assert (tmp_path / ".lore" / "skills" / "frontend-engineer" / "react-practices@v1.md").is_file()
    assert not (tmp_path / ".lore" / "skills" / "frontend-engineer" / "wrong-owner@v1.md").exists()


def test_finds_lore_from_a_nested_file() -> None:
    nested = PACK / "src" / "ui" / "Button.tsx"
    assert find_project(nested) == PACK

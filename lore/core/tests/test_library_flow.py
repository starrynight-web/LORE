"""Onboarding, call counts, and edits to personas, skills, and codebases."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from lore.core.codebases import (
    add_codebase,
    delete_codebase,
    list_codebases,
    remove_map,
    rename_codebase,
)
from lore.core.context import get_context
from lore.core.decisions import read_decision
from lore.core.inbox import add_text, adopt_inbox
from lore.core.onboarding import save, state
from lore.core.personas import (
    delete_persona,
    delete_skill,
    find_persona,
    locate_skill,
    update_persona,
    update_skill,
    write_persona,
    write_skill,
)
from lore.core.tests.pack import PACK
from lore.core.usage import summary
from lore.core.workspace import init_workspace


def test_empty_library_starts_at_the_greeting(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    assert state(tmp_path) == {"completed": False, "step": "welcome"}
    saved = save(tmp_path, completed=False, step="skills")
    assert saved["step"] == "skills"
    assert state(tmp_path)["completed"] is False


def test_a_library_with_personas_skips_the_greeting(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_persona(tmp_path, "Widget maker", "Makes widgets.", "You make widgets.\n")
    assert state(tmp_path)["completed"] is True


def test_finishing_setup_stays_finished(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    save(tmp_path, completed=True, step="codebase")
    assert state(tmp_path) == {"completed": True, "step": "done"}


def test_unknown_setup_step_is_refused(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    with pytest.raises(ValueError, match="setup step"):
        save(tmp_path, completed=False, step="billing")


def test_selected_waiting_skills_are_the_ones_filed(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    add_text(tmp_path, "a.md", "---\nname: Round widgets\ndescription: Prefer round.\n---\nKeep them round.\n")
    add_text(tmp_path, "b.md", "---\nname: Square widgets\ndescription: Prefer square.\n---\nKeep them square.\n")
    write_persona(tmp_path, "Widget maker", "Makes widgets.", "You make widgets.\n")
    ids = adopt_inbox(tmp_path, "persona:widget-maker", ["round-widgets"])
    assert ids == ["skill:widget-maker/round-widgets@v1"]
    assert (tmp_path / ".lore" / "inbox" / "square-widgets.md").is_file()


def test_persona_and_skill_can_be_edited_and_removed(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_persona(tmp_path, "Widget maker", "Makes widgets.", "You make widgets.\n")
    write_skill(
        tmp_path,
        "persona:widget-maker",
        "shape",
        title="Shape",
        summary="Prefer round widgets.",
        body="Keep the widget round.\n",
    )
    update_persona(tmp_path, "widget-maker", title="Widget lead", summary="Leads widget work.", status="stable")
    update_skill(tmp_path, "skill:widget-maker/shape@v1", summary="Prefer square widgets.", status="stable")
    persona = find_persona(tmp_path, "widget-maker")
    skill = locate_skill(tmp_path, "skill:widget-maker/shape@v1")
    assert persona is not None and persona.get("title") == "Widget lead"
    assert skill is not None and skill[1].get("summary") == "Prefer square widgets."
    delete_skill(tmp_path, "skill:widget-maker/shape@v1")
    assert locate_skill(tmp_path, "shape") is None
    kept = find_persona(tmp_path, "widget-maker")
    assert kept is not None
    assert kept.header["skill_ids"] == []
    delete_persona(tmp_path, "widget-maker")
    assert find_persona(tmp_path, "widget-maker") is None


def test_call_counts_name_the_agent_persona_and_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "app"
    shutil.copytree(PACK, project)
    monkeypatch.setenv("LORE_CLIENT", "Cursor")
    answer = get_context(project, "frontend-engineer", intent="tighten the button")
    record = read_decision(project, answer["decision_id"])
    assert record.header["client"] == "Cursor"
    counted = summary(project)
    assert counted["calls"] == 1
    assert counted["agents"] == [{"id": "Cursor", "name": "Cursor", "count": 1}]
    assert counted["personas"][0]["name"] == "Frontend engineer"
    assert counted["skills"][0]["count"] == 1


def test_codebase_registry_renames_and_removes_the_map(tmp_path: Path) -> None:
    library = tmp_path / "library"
    folder = tmp_path / "app"
    init_workspace(library)
    folder.mkdir()
    graph = folder / "graphify-out"
    graph.mkdir()
    (graph / "graph.json").write_text("{}", encoding="utf-8")
    (folder / ".lore").mkdir()
    (folder / ".lore" / "graph-status.json").write_text('{"state": "ready"}\n', encoding="utf-8")
    added = add_codebase(library, "Demo app", folder)
    renamed = rename_codebase(library, added["id"], "Demo")
    assert renamed["name"] == "Demo"
    assert list_codebases(library)[0]["path"] == str(folder.resolve())
    removed = delete_codebase(library, added["id"])
    remove_map(Path(removed["path"]))
    assert list_codebases(library) == []
    assert not graph.exists()
    assert not (folder / ".lore" / "graph-status.json").exists()
    assert (folder).is_dir()

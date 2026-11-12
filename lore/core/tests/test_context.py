from __future__ import annotations

import json
import shutil
from pathlib import Path

import jsonschema
import pytest
from lore.core.budget import _bytes_fallback, count_tokens
from lore.core.context import get_context
from lore.core.decisions import read_decision
from lore.core.personas import write_skill
from lore.core.tests.pack import PACK

SCHEMA = json.loads(Path("schemas/lore.result.v1.json").read_text(encoding="utf-8"))
BODY_MARKER = "BODY_REACT_STEPS_ONLY"
DRAFT_MARKER = "DRAFT_SECRET_STEPS"
BACKEND_MARKER = "BACKEND_ONLY_SKILL"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    dest = tmp_path / "app"
    shutil.copytree(PACK, dest)
    return dest


def test_token_count_uses_one_token_per_three_bytes_when_encoder_missing() -> None:
    assert _bytes_fallback("abcd") == 2
    assert count_tokens("abcd") >= 1


def test_task_call_returns_matching_skills_and_files(project: Path) -> None:
    envelope = get_context(project, "", intent="frontend engineer function components in the UI")
    jsonschema.validate(envelope, SCHEMA)
    assert envelope["verdict"] == "ok"
    ids = [item["id"] for item in envelope["items"]]
    assert ids == ["skill:frontend-engineer/react-practices@v1"]
    assert "persona:frontend-engineer" in envelope["data"]["personas"]
    assert "persona:backend-engineer" not in envelope["data"]["personas"]
    paths = [item["path"] for item in envelope["data"]["files"]]
    assert "src/ui/Button.tsx" in paths
    assert BODY_MARKER not in json.dumps(envelope)
    assert BACKEND_MARKER not in json.dumps(envelope)


def test_task_without_role_words_uses_file_path_hints(project: Path) -> None:
    envelope = get_context(
        project,
        "",
        intent="change the panel label to Saved",
        file_path="src/ui/Button.tsx",
    )
    jsonschema.validate(envelope, SCHEMA)
    assert "persona:frontend-engineer" in envelope["data"]["personas"]
    assert envelope["verdict"] in {"ok", "ok_with_notes"}


def test_task_without_role_or_path_lists_stable_personas(project: Path) -> None:
    envelope = get_context(project, "", intent="rename the leftover label")
    jsonschema.validate(envelope, SCHEMA)
    personas = envelope["data"]["personas"]
    assert "persona:frontend-engineer" in personas
    assert "persona:backend-engineer" in personas
    assert envelope["verdict"] == "ok_with_notes"
    assert "Available personas" in envelope["summary"]


def test_spaced_persona_name_resolves(project: Path) -> None:
    envelope = get_context(project, "frontend engineer")
    assert envelope["verdict"] == "ok"
    assert envelope["data"]["persona"] == "persona:frontend-engineer"
    assert envelope["items"][0]["id"] == "skill:frontend-engineer/react-practices@v1"


def test_frontend_returns_summaries_only(project: Path) -> None:
    envelope = get_context(project, "frontend-engineer", intent="build the settings form")
    jsonschema.validate(envelope, SCHEMA)
    assert envelope["verdict"] == "ok"
    assert envelope["directive"] == "proceed_and_cite"
    ids = [item["id"] for item in envelope["items"]]
    assert ids[:3] == [
        "skill:frontend-engineer/react-practices@v1",
        "skill:frontend-engineer/tailwind-rules@v1",
        "skill:frontend-engineer/ui-ux-pro-max@v1",
    ]
    assert all(item.startswith("chunk:") for item in ids[3:])
    blob = json.dumps(envelope)
    assert BODY_MARKER not in blob
    assert BACKEND_MARKER not in blob
    assert DRAFT_MARKER not in blob
    assert envelope["items"][0]["text"] == "Prefer function components and local state."
    assert envelope["budget"]["used"] <= 800
    assert envelope["budget"]["limit"] == 800
    saved = read_decision(project, envelope["decision_id"])
    assert saved.get("verdict") == "ok"


def test_draft_persona_asks_and_hides_steps(project: Path) -> None:
    envelope = get_context(project, "draft-persona")
    jsonschema.validate(envelope, SCHEMA)
    assert envelope["verdict"] == "abstain"
    assert envelope["directive"] == "ask_user"
    assert envelope["items"] == []
    assert "Approve" in envelope["summary"]
    assert DRAFT_MARKER not in json.dumps(envelope)


def test_unknown_persona(project: Path) -> None:
    envelope = get_context(project, "missing")
    assert envelope["verdict"] == "no_knowledge"
    assert envelope["directive"] == "proceed"
    assert envelope["items"] == []


def test_twelfth_skill_is_omitted(project: Path) -> None:
    for number in range(3, 13):
        write_skill(
            project,
            "frontend-engineer",
            f"extra-{number}@v1",
            title=f"Extra {number}",
            summary=f"Extra skill {number}.",
            body="not served in the list",
            status="stable",
        )
    envelope = get_context(project, "frontend-engineer")
    assert len(envelope["items"]) <= 8
    assert envelope["budget"]["used"] <= 800
    assert envelope["data"]["omitted"]
    assert "size cap" in envelope["summary"]


def test_second_call_writes_the_next_decision(project: Path) -> None:
    first = get_context(project, "frontend-engineer")
    second = get_context(project, "frontend-engineer")
    assert first["decision_id"] == "dec-0001"
    assert second["decision_id"] == "dec-0002"


def test_budget_counts_final_summary_items_and_files(project: Path) -> None:
    from lore.core.budget import context_content_text

    envelope = get_context(project, "", intent="frontend engineer function components in the UI")
    recomputed = count_tokens(
        context_content_text(
            envelope["summary"],
            envelope["items"],
            envelope["data"].get("files", []),
        )
    )
    assert envelope["budget"]["used"] == recomputed
    assert recomputed <= envelope["budget"]["limit"]


def test_omission_list_stays_out_of_the_summary(project: Path) -> None:
    for number in range(3, 15):
        write_skill(
            project,
            "frontend-engineer",
            f"extra-{number}@v1",
            title=f"Extra {number}",
            summary=f"Extra skill {number}.",
            body="not served in the list",
            status="stable",
        )
    envelope = get_context(project, "frontend-engineer")
    assert "items omitted because of the size cap" in envelope["summary"]
    for ident in envelope["data"]["omitted"]:
        assert ident not in envelope["summary"]
    assert envelope["data"]["omitted_count"] == len(envelope["data"]["omitted"])
    assert "metadata_truncated" not in envelope["data"]


def test_omitted_id_metadata_is_capped(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for number in range(3, 10):
        write_skill(
            project,
            "frontend-engineer",
            f"extra-{number}@v1",
            title=f"Extra {number}",
            summary=f"Extra skill {number}.",
            body="not served in the list",
            status="stable",
        )
    monkeypatch.setattr("lore.core.context.OMITTED_LIMIT", 3)
    envelope = get_context(project, "frontend-engineer")
    assert len(envelope["data"]["omitted"]) == 3
    assert envelope["data"]["omitted_count"] > 3
    assert envelope["data"]["metadata_truncated"] is True


def test_tiny_budget_still_returns_a_bounded_answer(project: Path) -> None:
    (project / ".lore" / "lore.config.yaml").write_text(
        "token_budget: 1\nmax_items: 8\n", encoding="utf-8"
    )
    envelope = get_context(project, "frontend-engineer")
    assert envelope["budget"]["used"] <= 1
    assert envelope["items"] == []


def test_result_reports_map_state(project: Path) -> None:
    envelope = get_context(project, "frontend-engineer")
    mapped = envelope["data"]["map"]
    assert mapped["advisory"] is True
    assert mapped["available"] is False
    assert mapped["state"] == "unavailable"
    assert isinstance(mapped["stale"], bool)


def test_task_result_always_lists_files(project: Path) -> None:
    envelope = get_context(project, "", intent="opaque task with no useful hints")
    assert envelope["data"]["files"] == []


def test_skills_dropped_by_the_budget_downgrade_the_directive(project: Path) -> None:
    (project / ".lore" / "lore.config.yaml").write_text(
        "token_budget: 8\nmax_items: 8\n", encoding="utf-8"
    )
    envelope = get_context(
        project, "", intent="frontend engineer function components in the UI"
    )
    assert all(item["kind"] != "skill" for item in envelope["items"])
    assert envelope["directive"] == "proceed"
    assert envelope["verdict"] != "ok"


def test_huge_file_names_do_not_bloat_the_summary(project: Path) -> None:
    huge = "components" + "x" * 400
    graph = json.loads(
        (project / "graphify-out" / "graph.json").read_text(encoding="utf-8")
    )
    graph["nodes"].append(
        {
            "id": "huge-node",
            "label": f"{huge}.tsx",
            "source_file": f"src/ui/{huge}.tsx",
        }
    )
    (project / "graphify-out" / "graph.json").write_text(
        json.dumps(graph), encoding="utf-8"
    )
    (project / ".lore" / "lore.config.yaml").write_text(
        "token_budget: 100\nmax_items: 8\n", encoding="utf-8"
    )
    envelope = get_context(project, "", intent=f"change the {huge} component")
    assert envelope["budget"]["used"] <= envelope["budget"]["limit"]
    assert huge not in envelope["summary"]
    for file_id in envelope["data"]["omitted"]:
        assert file_id not in envelope["summary"]


def test_unicode_summaries_still_fit_the_budget(project: Path) -> None:
    write_skill(
        project,
        "frontend-engineer",
        "unicode-practices@v1",
        title="コンポーネント",
        summary="🚀をむ。Unicode token boundaries must not break the budget.",
        body="\n",
        status="stable",
    )
    (project / ".lore" / "lore.config.yaml").write_text(
        "token_budget: 60\nmax_items: 8\n", encoding="utf-8"
    )
    envelope = get_context(project, "", intent=" components unicode")
    assert envelope["budget"]["used"] <= envelope["budget"]["limit"]

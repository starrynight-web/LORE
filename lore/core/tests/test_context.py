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

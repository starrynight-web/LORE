from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from lore.__main__ import main
from lore.core.context import get_context
from lore.core.decisions import read_decision
from lore.core.personas import write_persona, write_skill
from lore.core.usage import summary as usage_summary
from lore.mcp_server import build


def _seed_project(tmp_path: Path) -> Path:
    write_persona(
        tmp_path,
        "frontend-engineer",
        summary="Frontend work",
        body="Use React and CSS.",
        title="Frontend engineer",
        status="stable",
    )
    write_skill(
        tmp_path,
        "persona:frontend-engineer",
        "react-ui",
        title="React UI",
        summary="Use accessible buttons.",
        body="# Steps\nUse button elements.\n",
        status="stable",
    )
    return tmp_path


def test_token_telemetry_persisted_and_summarized(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    env = get_context(project, "frontend-engineer", "Build a button")
    dec = read_decision(project, str(env["decision_id"]))
    assert dec.header["tokens_used"] == env["budget"]["used"]
    assert dec.header["token_budget"] == env["budget"]["limit"]

    stats = usage_summary(project)
    assert stats["calls"] == 1
    assert stats["tokens"]["tracked_calls"] == 1
    assert stats["tokens"]["total"] == env["budget"]["used"]
    assert stats["tokens"]["avg"] == env["budget"]["used"]
    assert stats["tokens"]["max"] == env["budget"]["used"]
    assert len(stats["tokens"]["series"]) == 1
    assert stats["tokens"]["series"][0]["id"] == env["decision_id"]
    assert stats["recent"][0]["tokens_used"] == env["budget"]["used"]


def test_cli_skill_persona_govern_and_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".lore").mkdir()
    monkeypatch.chdir(tmp_path)

    # Create persona via CLI
    assert main(["persona", "create", "backend", "--summary", "API work", "--json"]) == 0
    created_persona = json.loads(capsys.readouterr().out)
    assert created_persona["id"] == "persona:backend"
    assert created_persona["status"] == "draft"

    # Add skill text to inbox via CLI and adopt it
    assert main(["skill", "add", "--name", "sql-safe", "--text", "---\ntitle: SQL Safe\nsummary: Use parameterized queries\n---\nAlways bind params.\n", "--json"]) == 0
    inbox_item = json.loads(capsys.readouterr().out)
    assert main(["skill", "adopt", inbox_item["id"], "--persona", "backend", "--json"]) == 0
    adopted = json.loads(capsys.readouterr().out)
    assert adopted["status"] == "draft"

    # Approve persona & skill via govern approve and skill approve
    assert main(["govern", "approve", "persona:backend", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "stable"

    assert main(["skill", "approve", adopted["id"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "stable"

    # Call get_context and check stats CLI
    get_context(tmp_path, "backend", "query sql")
    assert main(["stats", "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["calls"] == 1
    assert stats["tokens"]["total"] > 0


def test_mcp_full_autonomous_workflow(tmp_path: Path) -> None:
    (tmp_path / ".lore").mkdir()
    mcp = build(project=tmp_path, surface="full")

    async def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        res = await mcp.call_tool(name, args)
        assert res.structured_content is not None
        return res.structured_content

    async def _run() -> dict[str, Any]:
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        expected = {
            "search_skills",
            "install_skill",
            "list_inbox",
            "list_skills",
            "setup_persona",
            "approve_item",
            "check_security",
            "check_freshness",
            "get_telemetry",
        }
        assert expected.issubset(names)

        # Create & approve persona
        p_data = await _call(
            "setup_persona",
            {"name": "qa-engineer", "summary": "Testing", "approve": True},
        )
        assert p_data["id"] == "persona:qa-engineer"
        assert p_data["status"] == "stable"

        # Install skill from text directly into persona
        s_data = await _call(
            "install_skill",
            {
                "name": "unit-tests",
                "content": "---\ntitle: Unit Tests\nsummary: Write pytest tests.\n---\nTest edge cases.\n",
                "persona": "qa-engineer",
            },
        )
        skill_id = s_data["adopted"][0]

        # Security + freshness + approve
        sec = await _call("check_security", {"item_id": skill_id})
        assert sec["items"][0]["findings"] == []

        fresh = await _call("check_freshness", {"item_id": skill_id})
        assert fresh["items"][0]["status"] == "current"

        app = await _call("approve_item", {"item_id": skill_id})
        assert app["approved"] is True
        assert app["status"] == "stable"

        # Context + telemetry
        await _call("get_context", {"persona": "qa-engineer", "intent": "write tests"})
        tel = await _call("get_telemetry", {})
        assert tel["calls"] == 1
        assert tel["tokens"]["total"] > 0
        return tel

    result = asyncio.run(_run())
    assert result["tokens"]["tracked_calls"] == 1

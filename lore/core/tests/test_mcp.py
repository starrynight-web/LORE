from __future__ import annotations

import asyncio
import json
import shutil
import socket
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from lore.core.personas import write_skill
from lore.core.tests.pack import PACK
from lore.mcp_server import build

BODY_MARKER = "BODY_REACT_STEPS_ONLY"


def _copy(tmp_path: Path) -> Path:
    dest = tmp_path / "app"
    shutil.copytree(PACK, dest)
    return dest


def _payload(result: object) -> object:
    structured = getattr(result, "structured_content", None) or getattr(result, "data", None)
    if isinstance(structured, dict) and set(structured) == {"result"}:
        structured = structured["result"]
    if structured is not None:
        return structured
    content = getattr(result, "content", None)
    if content:
        text = getattr(content[0], "text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return result


def test_mcp_tools_do_not_bind_a_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _copy(tmp_path)

    def refuse_bind(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("MCP test tried to bind a TCP port")

    monkeypatch.setattr(socket.socket, "bind", refuse_bind)

    async def call() -> None:
        async with Client(build(project, surface="full")) as client:
            context = _payload(await client.call_tool("get_context", {"persona": "frontend-engineer"}))
            assert isinstance(context, dict)
            ids = [item["id"] for item in context["items"]]
            assert ids[:2] == [
                "skill:frontend-engineer/react-practices@v1",
                "skill:frontend-engineer/tailwind-rules@v1",
            ]
            skill = _payload(
                await client.call_tool(
                    "get_skill",
                    {"name": "react-practices", "persona": "frontend-engineer"},
                )
            )
            assert isinstance(skill, dict)
            assert BODY_MARKER in skill["body"]
            personas = _payload(await client.call_tool("list_personas", {}))
            assert isinstance(personas, list)
            names = [row["id"] for row in personas]
            assert "persona:draft-persona" not in names
            assert "persona:frontend-engineer" in names
            ingested = _payload(
                await client.call_tool(
                    "ingest",
                    {
                        "persona": "frontend-engineer",
                        "filename": "motion@v1",
                        "content": "Keep motion short.",
                        "title": "Motion",
                        "summary": "Short motion.",
                        "idempotency_key": "once",
                    },
                )
            )
            again = _payload(
                await client.call_tool(
                    "ingest",
                    {
                        "persona": "frontend-engineer",
                        "filename": "motion@v1",
                        "content": "A second copy.",
                        "idempotency_key": "once",
                    },
                )
            )
            assert ingested == again
            later = _payload(await client.call_tool("get_context", {"persona": "frontend-engineer"}))
            assert isinstance(later, dict)
            assert "skill:frontend-engineer/motion@v1" not in [item["id"] for item in later["items"]]
            traced = _payload(await client.call_tool("trace", {"decision_id": context["decision_id"]}))
            assert isinstance(traced, dict)
            assert traced["header"]["verdict"] == "ok"

    asyncio.run(call())


def test_coding_surface_exposes_quality_loop_tools(tmp_path: Path) -> None:
    project = _copy(tmp_path)

    async def call() -> None:
        async with Client(build(project, surface="coding")) as client:
            tools = await client.list_tools()
            names = sorted(tool.name for tool in tools)
            assert names == [
                "check_applied",
                "get_context",
                "get_skill",
                "log_decision",
                "map_codebase",
            ]
            context = _payload(
                await client.call_tool(
                    "get_context",
                    {"persona": "frontend-engineer", "intent": "button label"},
                )
            )
            assert isinstance(context, dict)
            cite_ids = context["data"]["cite_ids"]
            assert cite_ids
            checked = _payload(
                await client.call_tool(
                    "check_applied",
                    {"decision_id": context["decision_id"], "rule_ids": cite_ids},
                )
            )
            assert isinstance(checked, dict)
            assert checked["status"] == "pass"
            logged = _payload(
                await client.call_tool(
                    "log_decision",
                    {"decision_id": context["decision_id"], "outcome": "edited button"},
                )
            )
            assert isinstance(logged, dict)
            assert logged["status"] == "recorded"
            skill = _payload(
                await client.call_tool(
                    "get_skill",
                    {"name": "react-practices", "persona": "frontend-engineer"},
                )
            )
            assert isinstance(skill, dict)
            assert BODY_MARKER in skill["body"]
            assert skill["has_more"] is False

    asyncio.run(call())


def test_coding_get_skill_paginates_a_unicode_body(tmp_path: Path) -> None:
    import hashlib

    project = _copy(tmp_path)
    body = "λ" * 7000 + "é" * 5000 + "final step\n"
    write_skill(
        project,
        "frontend-engineer",
        "long-steps@v1",
        title="Long steps",
        summary="A long body.",
        body=body,
        status="stable",
    )
    want_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()

    async def call() -> None:
        async with Client(build(project, surface="coding")) as client:
            first = _payload(
                await client.call_tool(
                    "get_skill",
                    {"name": "long-steps", "persona": "frontend-engineer"},
                )
            )
            assert isinstance(first, dict)
            assert first["offset"] == 0
            assert first["has_more"] is True
            assert first["next_offset"] == 12000
            assert len(first["body"]) == 12000
            assert first["body_sha256"] == want_sha
            second = _payload(
                await client.call_tool(
                    "get_skill",
                    {
                        "name": "long-steps",
                        "persona": "frontend-engineer",
                        "offset": first["next_offset"],
                        "limit": 24000,
                    },
                )
            )
            assert isinstance(second, dict)
            assert second["has_more"] is False
            assert second["next_offset"] is None
            assert second["body_sha256"] == want_sha
            assert first["body"] + second["body"] == body
            terminal = _payload(
                await client.call_tool(
                    "get_skill",
                    {
                        "name": "long-steps",
                        "persona": "frontend-engineer",
                        "offset": len(body) + 5,
                    },
                )
            )
            assert isinstance(terminal, dict)
            assert terminal["body"] == ""
            assert terminal["has_more"] is False
            assert terminal["next_offset"] is None

    asyncio.run(call())


def test_coding_get_skill_rejects_bad_pages_and_hidden_skills(tmp_path: Path) -> None:
    project = _copy(tmp_path)

    async def call() -> None:
        async with Client(build(project, surface="coding")) as client:
            for args in (
                {"name": "react-practices", "persona": "frontend-engineer", "offset": -1},
                {"name": "react-practices", "persona": "frontend-engineer", "limit": 0},
                {"name": "react-practices", "persona": "frontend-engineer", "limit": 25000},
            ):
                with pytest.raises(ToolError):
                    await client.call_tool("get_skill", args)
            for bad_args in (
                {"name": "secret-steps", "persona": "draft-persona"},
                {"name": "secret-steps"},
                {"name": "wrong-owner", "persona": "frontend-engineer"},
                {"name": "wrong-owner", "persona": "backend-engineer"},
                {"name": "not-a-skill"},
            ):
                with pytest.raises(ToolError):
                    await client.call_tool("get_skill", bad_args)

    asyncio.run(call())


def test_coding_get_skill_disambiguates_short_names(tmp_path: Path) -> None:
    project = _copy(tmp_path)
    write_skill(
        project,
        "backend-engineer",
        "react-practices",
        title="Backend react practices",
        summary="Backend-only react guidance.",
        body="BACKEND_REACT_VARIANT",
        status="stable",
    )

    async def call() -> None:
        async with Client(build(project, surface="coding")) as client:
            with pytest.raises(ToolError):
                await client.call_tool("get_skill", {"name": "react-practices"})
            frontend = _payload(
                await client.call_tool(
                    "get_skill",
                    {"name": "react-practices", "persona": "frontend-engineer"},
                )
            )
            assert isinstance(frontend, dict)
            assert frontend["id"] == "skill:frontend-engineer/react-practices@v1"
            assert BODY_MARKER in frontend["body"]
            backend = _payload(
                await client.call_tool(
                    "get_skill",
                    {"name": "react-practices", "persona": "backend-engineer"},
                )
            )
            assert isinstance(backend, dict)
            assert backend["id"] == "skill:backend-engineer/react-practices@v1"
            canonical = _payload(
                await client.call_tool(
                    "get_skill",
                    {"name": "skill:backend-engineer/react-practices@v1"},
                )
            )
            assert isinstance(canonical, dict)
            assert canonical["id"] == "skill:backend-engineer/react-practices@v1"

    asyncio.run(call())

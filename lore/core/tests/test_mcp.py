from __future__ import annotations

import asyncio
import json
import shutil
import socket
from pathlib import Path

import pytest
from fastmcp import Client
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
        async with Client(build(project)) as client:
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

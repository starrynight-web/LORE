"""One live Graphify extract. Not part of CI.

Run from the repo root:

    .venv/bin/python scripts/live_graph_check.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "examples" / "persona-pack"
DEST = ROOT / ".tmp" / "live-graph-check"
GRAPHIFY = ROOT / ".venv" / "bin" / "graphify"


def fail(message: str) -> None:
    print(f"fail: {message}", file=sys.stderr)
    raise SystemExit(1)


def extract() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(PACK, DEST)
    shutil.rmtree(DEST / "graphify-out", ignore_errors=True)
    exe = GRAPHIFY if GRAPHIFY.is_file() else Path(shutil.which("graphify") or "")
    if not exe.is_file():
        fail("graphify is not installed")
    result = subprocess.run(
        [str(exe), "extract", str(DEST), "--code-only", "--out", str(DEST)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        fail(detail[-1] if detail else "graphify extract failed")
    path = DEST / "graphify-out" / "graph.json"
    if not path.is_file():
        fail("graph.json was not written")
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("schema_version")
    graph = data.get("graph")
    if isinstance(graph, dict) and version is None:
        version = graph.get("schema_version")
    if version not in {1, "1"}:
        fail(f"schema version {version}")
    print("pass: schema version 1")


async def tools() -> None:
    from fastmcp import Client
    from lore.mcp_server import build

    async with Client(build(DEST)) as client:
        context = await client.call_tool(
            "get_context",
            {
                "persona": "frontend-engineer",
                "file_path": "src/ui/Button.tsx",
                "intent": "UI change",
            },
        )
        payload = _payload(context)
        if not isinstance(payload, dict):
            fail("get_context did not return an object")
        blob = json.dumps(payload)
        if "Button.tsx" not in blob or "theme.ts" not in blob:
            fail("get_context missed Button.tsx or theme.ts")
        print("pass: get_context names Button.tsx and theme.ts")
        for name, arguments in (
            ("get_skill", {"name": "react-practices", "persona": "frontend-engineer"}),
            ("list_personas", {}),
            ("map_status", {}),
            ("locate", {"intent": "UI change"}),
        ):
            result = _payload(await client.call_tool(name, arguments))
            if result is None:
                fail(f"{name} returned nothing")
            print(f"pass: {name}")
        located = _payload(await client.call_tool("locate", {"intent": "UI change"}))
        if not isinstance(located, dict):
            fail("locate did not return an object")
        paths = [item.get("path", "") for item in located.get("files", [])]
        if "src/ui/Button.tsx" not in paths or "src/ui/theme.ts" not in paths:
            fail(f"locate paths {paths}")
        if any("mcp.json" in path for path in paths):
            fail("locate returned the MCP config")
        print("pass: locate stays on the UI files")


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


def main() -> None:
    extract()
    asyncio.run(tools())
    print("live graph check passed")


if __name__ == "__main__":
    main()

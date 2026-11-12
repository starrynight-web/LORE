#!/usr/bin/env python3
"""Exercise the container runtime end to end against prebuilt images.

Uses `lore-solo container` (the same path editors take) with temporary
workspace/library fixtures. Asserts persistence, non-root write ownership,
the real stdio MCP receipt flow, real Graphify mapping, the published setup
site with settings persistence, and that MCP keeps working after setup
stops. Only pre-existing images are used; missing Docker or images fails
clearly — never a silent skip.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []
EVIDENCE: dict[str, Any] = {"checks": []}

API_PORT = 7421


def check(name: str, ok: bool, detail: str = "") -> None:
    EVIDENCE["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        FAILURES.append(name)


def _docker() -> str:
    docker = shutil.which("docker")
    if docker is None:
        print("docker is not on PATH", file=sys.stderr)
        raise SystemExit(2)
    return docker


def _require_image(docker: str, image: str) -> None:
    probe = subprocess.run(
        [docker, "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    if probe.returncode != 0:
        print(
            f"image {image} is not available locally; build it first",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _port_busy(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _lore_argv(mode: str, image: str, workspace: Path, library: Path, port: int = 0) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "lore",
        "container",
        mode,
        "--image",
        image,
        "--workspace",
        str(workspace),
        "--library",
        str(library),
    ]
    if port:
        command += ["--port", str(port)]
    return command


def _fixture(workspace: Path, library: Path) -> None:
    """Approved persona/skill content only, in the mounted library."""
    workspace.mkdir(parents=True)
    store = library / ".lore"
    pack = REPO / "examples" / "persona-pack" / ".lore"
    for kind in ("personas", "skills"):
        source = pack / kind
        if source.is_dir():
            shutil.copytree(source, store / kind)


def _stdio_env() -> dict[str, str]:
    # HOME must stay the real one: rootless Podman keeps image storage under
    # ~/.local/share/containers, so a fixture HOME hides every local image.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "LORE_CLIENT": "container-smoke",
    }
    passthrough = (
        "SYSTEMROOT",
        "WINDIR",
        "TMPDIR",
        "TEMP",
        "TMP",
        "XDG_RUNTIME_DIR",
        "DOCKER_HOST",
        "CONTAINER_HOST",
        "DOCKER_CONFIG",
    )
    for key in passthrough:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _probe(url: str, key: str = "", method: str = "GET", payload: dict | None = None) -> int:
    for attempt in range(10):
        data = None
        request = urllib.request.Request(url, method=method)
        if key:
            request.add_header("X-Lore-Key", key)
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, data=data, timeout=3) as response:
                return int(response.status)
        except urllib.error.HTTPError as exc:
            return int(exc.code)
        except (urllib.error.URLError, OSError):
            if attempt == 9:
                return 0
            time.sleep(0.5)
    return 0


def _read_until(
    process: subprocess.Popen[str], marker: str, timeout: float
) -> tuple[str, list[str]]:
    """Read child stdout until `marker`, with a real deadline."""
    lines: list[str] = []
    found = ""
    out: queue.Queue[str | None] = queue.Queue()
    stream = process.stdout

    def pump() -> None:
        try:
            if stream is not None:
                for line in stream:
                    out.put(line)
        finally:
            out.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = out.get(timeout=0.2)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if line is None:
            break
        lines.append(line)
        if marker in line:
            found = line
            break
    return found, lines


def _decision_ids(library: Path) -> set[str]:
    return {p.name for p in library.glob(".lore/decisions/*.md")}


async def _session(
    mcp_argv: list[str],
    env: dict[str, str],
    full_argv: list[str],
    port: int,
    library_runtime: str,
    workspace_runtime: str,
    artifacts: Path,
) -> dict[str, Any]:
    """One MCP client session spanning a setup container start/stop cycle."""
    from fastmcp import Client

    config = {
        "mcpServers": {
            "lore": {
                "command": mcp_argv[0],
                "args": mcp_argv[1:],
                "env": env,
            }
        }
    }
    seen: dict[str, Any] = {}
    async with Client(config) as client:
        context = await client.call_tool(
            "get_context",
            {"intent": "react component state", "file_path": "src/App.tsx"},
        )
        seen["context"] = context.data
        cite_ids = list((context.data.get("data") or {}).get("cite_ids") or [])
        skill = await client.call_tool(
            "get_skill", {"name": "frontend-engineer/react-practices@v1"}
        )
        seen["skill"] = skill.data
        decision_id = str(context.data.get("decision_id", ""))
        applied = await client.call_tool(
            "check_applied", {"decision_id": decision_id, "rule_ids": cite_ids}
        )
        seen["applied"] = applied.data
        logged = await client.call_tool(
            "log_decision",
            {"decision_id": decision_id, "outcome": "applied"},
        )
        seen["logged"] = logged.data

        for attempt in (1, 2):
            if not full_argv:
                break
            process = await asyncio.to_thread(
                subprocess.Popen,
                full_argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            key = ""
            lines: list[str] = []
            try:
                banner, lines = _read_until(process, "?key=", 90)
                if banner:
                    key = banner.split("?key=", 1)[-1].strip()
                check(f"container setup banner (run {attempt})", bool(key))
                if not key:
                    break
                check(
                    f"container setup root (run {attempt})",
                    _probe(f"http://127.0.0.1:{port}/") == 200,
                )
                browse = urllib.parse.quote(workspace_runtime)
                check(
                    f"container api unkeyed 401 (run {attempt})",
                    _probe(f"http://127.0.0.1:{port}/api/browse?path={browse}") == 401,
                )
                check(
                    f"container api keyed 200 (run {attempt})",
                    _probe(f"http://127.0.0.1:{port}/api/browse?path={browse}", key) == 200,
                )
                settings_url = f"http://127.0.0.1:{port}/api/settings"
                if attempt == 1:
                    code = _settings_write(
                        settings_url, key, library_runtime,
                        {"token_budget": 640, "max_items": 6},
                    )
                    check("container settings POST", code == 200, str(code))
                else:
                    saved = _settings_read(settings_url, key, library_runtime)
                    check(
                        "container settings persisted",
                        saved.get("token_budget") == 640
                        and saved.get("max_items") == 6,
                        str(saved)[:150],
                    )
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                check(
                    f"container setup stops (run {attempt})",
                    process.returncode in {0, 130},
                    str(process.returncode),
                )
                _drain, extra = _read_until(process, "\x00never", 2)
                lines.extend(extra)
                (artifacts / f"setup-run{attempt}.log").write_text(
                    "".join(lines), encoding="utf-8"
                )

        after = await client.call_tool(
            "get_context",
            {"intent": "react component state", "file_path": "src/App.tsx"},
        )
        seen["after"] = after.data
    return seen


def _settings_write(url: str, key: str, project: str, payload: dict[str, int]) -> int:
    request = urllib.request.Request(url, method="POST")
    request.add_header("X-Lore-Key", key)
    request.add_header("X-Lore-Project", project)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(
            request, data=json.dumps(payload).encode("utf-8"), timeout=5
        ) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError):
        return 0


def _settings_read(url: str, key: str, project: str) -> dict[str, Any]:
    request = urllib.request.Request(url)
    request.add_header("X-Lore-Key", key)
    request.add_header("X-Lore-Project", project)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return {}


def _assert_receipt_flow(seen: dict[str, Any]) -> None:
    context = seen.get("context") or {}
    check("container decision receipt", bool(context.get("decision_id")))
    check(
        "container verdict ok",
        str(context.get("verdict")) == "ok",
        str(context.get("verdict")),
    )
    cite_ids = list((context.get("data") or {}).get("cite_ids") or [])
    check("container cite_ids nonempty", bool(cite_ids), ",".join(cite_ids)[:150])
    skill = seen.get("skill") or {}
    check(
        "container skill body",
        "function components" in str(skill.get("body", "")),
    )
    applied = seen.get("applied") or {}
    check(
        "container check_applied pass",
        applied.get("check_kind") == "citation_receipt"
        and applied.get("code_verified") is False
        and str(applied.get("status")) == "pass",
        str(applied.get("status")),
    )
    logged = seen.get("logged") or {}
    check(
        "container log_decision",
        str(logged.get("status")) == "recorded",
        str(logged.get("status")),
    )
    after = seen.get("after") or {}
    check(
        "mcp usable after setup stops",
        bool(after.get("decision_id")),
        str(after.get("verdict")),
    )


def _map_flow(mcp_image: str, workspace: Path, library: Path) -> None:
    repo = workspace / "fixture-repo"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "app.py").write_text(
        "import util\n\ndef main():\n    return util.helper()\n", encoding="utf-8"
    )
    (repo / "src" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    argv = _lore_argv("map", mcp_image, repo, library)
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=300, check=False
    )
    graph_ok = False
    graph_path = repo / "graphify-out" / "graph.json"
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        graph_ok = bool(graph.get("nodes"))
    except (OSError, json.JSONDecodeError):
        graph_ok = False
    check(
        "container map exits 0",
        result.returncode == 0,
        (result.stdout + result.stderr)[-200:],
    )
    check("container map graph nonempty", graph_ok)


def _write_evidence(artifacts: Path) -> Path:
    EVIDENCE["ok"] = (
        EVIDENCE.get("completed") is True and bool(EVIDENCE.get("checks")) and not FAILURES
    )
    out = artifacts / "smoke-container.json"
    out.write_text(json.dumps(EVIDENCE, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    FAILURES.clear()
    EVIDENCE.clear()
    EVIDENCE["checks"] = []
    EVIDENCE["completed"] = False
    parser = argparse.ArgumentParser(prog="smoke_container.py")
    parser.add_argument("--mcp-image", required=True)
    parser.add_argument("--full-image", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args(argv)
    docker = _docker()
    _require_image(docker, args.mcp_image)
    _require_image(docker, args.full_image)
    EVIDENCE["mcp_image"] = args.mcp_image
    EVIDENCE["full_image"] = args.full_image
    args.artifacts.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix="lore-ctsmoke-"))
    try:
        workspace = work / "workspace"
        library = work / "library"
        _fixture(workspace, library)
        before_ids = _decision_ids(library)

        port = _free_port()
        if _port_busy(API_PORT):
            print(
                f"setup API port {API_PORT} is already in use; aborting smoke",
                file=sys.stderr,
            )
            raise SystemExit(2)

        mcp_argv = _lore_argv("mcp", args.mcp_image, workspace, library)
        full_argv = _lore_argv("setup", args.full_image, workspace, library, port)
        try:
            seen = asyncio.run(
                _session(
                    mcp_argv,
                    _stdio_env(),
                    full_argv,
                    port,
                    "/library",
                    "/workspace",
                    args.artifacts,
                )
            )
        except Exception as exc:  # noqa: BLE001 - smoke must report, not traceback
            check("container mcp stdio", False, str(exc)[:300])
            seen = {}
        else:
            check("container mcp stdio", True)
            _assert_receipt_flow(seen)

        after_ids = _decision_ids(library)
        new_ids = after_ids - before_ids
        check("decision persisted under mounted library", bool(new_ids))
        if new_ids and os.name != "nt" and hasattr(os, "getuid"):
            owner = next(iter(library.glob(".lore/decisions/*.md"))).stat().st_uid
            check(
                "writes owned by host uid",
                owner == os.getuid(),
                f"uid={owner} host={os.getuid()}",
            )

        # A second session must produce strictly new decision ids.
        try:
            asyncio.run(
                _session(
                    mcp_argv,
                    _stdio_env(),
                    [],  # no setup on the second pass
                    port,
                    "/library",
                    "/workspace",
                    args.artifacts,
                )
            )
        except Exception as exc:  # noqa: BLE001 - report, never silently pass
            check("second mcp session", False, str(exc)[:200])
        later_ids = _decision_ids(library)
        check(
            "new decision ids across runs",
            bool(later_ids - after_ids),
            f"{len(after_ids)} -> {len(later_ids)}",
        )

        _map_flow(args.mcp_image, workspace, library)

        leftover = subprocess.run(
            [
                docker,
                "ps",
                "--filter",
                f"label=io.lore.workspace={workspace}",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        running = [n for n in leftover.stdout.splitlines() if n.strip()]
        check(
            "no owned containers left running",
            leftover.returncode == 0 and not running,
            ",".join(running) or leftover.stderr[-200:],
        )
        EVIDENCE["completed"] = True
    finally:
        shutil.rmtree(work, ignore_errors=True)
        out = _write_evidence(args.artifacts)
        print(f"wrote {out}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())

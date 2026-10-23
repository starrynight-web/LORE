"""Approve a draft through Django, then read it after that process is gone."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _request(port: int, key: str, method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"X-Lore-Key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_until_up(port: int, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.time() + 15
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"Django exited early: {last}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = str(exc)
        time.sleep(0.15)
    raise AssertionError(f"Django did not start: {last}")


def _server(port: int, key: str, workspace: Path | None = None) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["LORE_SETUP_KEY"] = key
    env["LORE_SETUP_PORT"] = str(port)
    env["LORE_COMMAND"] = "lore"
    env["DJANGO_SETTINGS_MODULE"] = "lore.setup.settings"
    if workspace is not None:
        env["LORE_WORKSPACE"] = str(workspace)
        env["LORE_LIBRARY"] = str(workspace)
    return subprocess.Popen(
        [sys.executable, "-m", "lore.setup_cmd", "--serve-api"],
        env=env,
        cwd=ROOT,
    )


def test_missing_key_and_outside_home() -> None:
    port = _free_port()
    key = "phase4-key"
    proc = _server(port, key)
    try:
        _wait_until_up(port, proc)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/browse", timeout=2)
            raise AssertionError("browse without a key should fail")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            assert exc.code == 401
            assert "Open the link printed in the terminal." in body
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/browse?path=/etc",
            headers={"X-Lore-Key": key},
        )
        try:
            urllib.request.urlopen(request, timeout=2)
            raise AssertionError("browse outside home should fail")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_approve_survives_after_django_stops() -> None:
    project = ROOT / ".tmp" / "setup-approve"
    if project.exists():
        shutil.rmtree(project)
    project.mkdir(parents=True)
    port = _free_port()
    key = "phase4-approve"
    proc = _server(port, key, project)
    try:
        _wait_until_up(port, proc)
        chosen = _request(port, key, "POST", "/api/workspace", {"path": str(project)})
        assert chosen["project"] == str(project.resolve())
        persona = _request(
            port,
            key,
            "POST",
            "/api/personas",
            {"name": "Widget maker", "summary": "Makes widgets.", "steps": "You make widgets."},
        )
        skill = _request(
            port,
            key,
            "POST",
            f"/api/personas/{persona['id']}/skills",
            {
                "name": "Widget shape",
                "summary": "Prefer round widgets.",
                "steps": "1. Keep the widget round.",
            },
        )
        assert skill["status"] == "draft"
        _request(port, key, "POST", f"/api/items/{persona['id']}/approve")
        approved = _request(port, key, "POST", f"/api/items/{skill['id']}/approve")
        assert approved["status"] == "stable"
        config = (project / ".lore" / "lore.config.yaml").read_text(encoding="utf-8")
        assert "token_budget: 800" in config
        saved = _request(
            port,
            key,
            "POST",
            "/api/settings",
            {"token_budget": 800, "max_items": 8},
        )
        assert saved == {"token_budget": 800, "max_items": 8}
        catalog = _request(port, key, "GET", "/api/catalog")
        titles = {row["title"] for row in catalog["personas"]}
        assert "Frontend engineer" in titles
        assert "Backend engineer" in titles
        added = _request(port, key, "POST", "/api/catalog/backend-engineer")
        assert added["status"] == "stable"
        install = _request(port, key, "GET", "/api/connect")
        assert "connect" in install["command"]
        assert "Install Lore" in install["prompt"]
        written = _request(port, key, "POST", "/api/connect")
        assert written["mcpServers"]["lore"]["command"] == "lore"
        assert written["mcpServers"]["lore"]["args"] == ["mcp"]
        assert (project / ".cursor" / "mcp.json").is_file()
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    script = (
        "import json,sys\n"
        "from pathlib import Path\n"
        "from lore.core.context import get_context\n"
        "print(json.dumps(get_context(Path(sys.argv[1]), sys.argv[2])))\n"
    )
    raw = subprocess.check_output(
        [sys.executable, "-c", script, str(project), "widget-maker"],
        text=True,
    )
    envelope = json.loads(raw)
    assert envelope["verdict"] == "ok"
    assert envelope["items"][0]["text"] == "Prefer round widgets."
    shutil.rmtree(project, ignore_errors=True)


def test_provider_key_is_not_returned() -> None:
    project = ROOT / ".tmp" / "setup-provider"
    if project.exists():
        shutil.rmtree(project)
    project.mkdir(parents=True)
    port = _free_port()
    key = "phase-provider"
    secret = "groq-test-key-9876"
    proc = _server(port, key, project)
    try:
        _wait_until_up(port, proc)
        saved = _request(port, key, "POST", "/api/provider", {"provider": "groq", "key": secret})
        assert saved["last4"] == "9876"
        assert secret not in json.dumps(saved)
        shown = _request(port, key, "GET", "/api/provider")
        assert shown["configured"] is True
        assert shown["model"] == "llama-3.3-70b-versatile"
        assert secret not in json.dumps(shown)
        changed = _request(port, key, "POST", "/api/provider/models", {"model": "llama-3.1-8b-instant"})
        assert changed["model"] == "llama-3.1-8b-instant"
        assert secret not in json.dumps(changed)
        try:
            _request(port, key, "POST", "/api/provider/models", {"model": "../secret"})
            raise AssertionError("a path is not a model id")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        shutil.rmtree(project, ignore_errors=True)


def test_banner_prints_local_url(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    from lore import setup_cmd

    monkeypatch.setattr(setup_cmd, "start_processes", lambda _key: [])
    setup_cmd.run([])
    printed = capsys.readouterr().out
    assert "Lore setup is running." in printed
    assert "Open http://127.0.0.1:3000/?key=" in printed

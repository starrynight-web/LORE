"""Register Lore without touching the real home directory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lore.connect import install_command, mcp_entry, register_agents, windows_command


def test_uvx_is_the_command_when_nothing_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LORE_COMMAND", raising=False)
    monkeypatch.delenv("LORE_LAUNCHER", raising=False)
    monkeypatch.setattr("lore.connect.Path.home", lambda: tmp_path)
    monkeypatch.setattr("lore.connect.shutil.which", lambda _name: None)
    assert mcp_entry("cursor") == {"command": "uvx", "args": ["lore-solo", "mcp"]}
    assert install_command() == "uvx lore-solo connect"
    assert windows_command("uvx lore-solo connect") == "uvx lore-solo connect"
    assert windows_command("scripts/lore-solo connect") == "scripts/lore-solo.ps1 connect"


def test_mcp_entry_is_a_local_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_COMMAND", "/opt/lore/bin/lore")
    assert mcp_entry("cursor") == {"command": "/opt/lore/bin/lore", "args": ["mcp"]}
    vscode = mcp_entry("vscode")
    assert vscode["command"] == "/opt/lore/bin/lore"
    assert vscode["args"] == ["mcp"]
    assert vscode["type"] == "stdio"


def test_register_keeps_servers_already_in_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LORE_COMMAND", "lore")
    cursor = tmp_path / ".cursor" / "mcp.json"
    cursor.parent.mkdir()
    cursor.write_text(
        json.dumps({"mcpServers": {"other": {"command": "other"}}}) + "\n",
        encoding="utf-8",
    )
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text(
        'model = "keep"\n\n[mcp_servers.other]\ncommand = "stay"\n',
        encoding="utf-8",
    )
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude.json").write_text("{", encoding="utf-8")

    result = register_agents(tmp_path, system="linux")

    saved = json.loads(cursor.read_text(encoding="utf-8"))
    assert saved["mcpServers"]["other"]["command"] == "other"
    assert saved["mcpServers"]["lore"]["command"] == "lore"
    assert saved["mcpServers"]["lore"]["args"] == ["mcp"]
    toml = (codex / "config.toml").read_text(encoding="utf-8")
    assert 'model = "keep"' in toml
    assert "[mcp_servers.other]" in toml
    assert "[mcp_servers.lore]" in toml
    assert 'command = "lore"' in toml
    assert 'args = ["mcp"]' in toml
    assert str(cursor) in result["written"]
    assert any(item.startswith("Claude Code:") for item in result["skipped"])
    assert not (tmp_path / ".config" / "Claude").exists()

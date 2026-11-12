"""Register Lore without touching the real home directory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lore.connect import (
    MCP_SERVER_NAME,
    install_command,
    mcp_entry,
    register_agents,
    windows_command,
)


def test_uvx_is_the_command_when_nothing_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LORE_COMMAND", raising=False)
    monkeypatch.delenv("LORE_LAUNCHER", raising=False)
    monkeypatch.delenv("LORE_WORKSPACE", raising=False)
    monkeypatch.setattr("lore.connect.Path.home", lambda: tmp_path)
    monkeypatch.setattr("lore.connect.shutil.which", lambda _name: None)
    monkeypatch.chdir(tmp_path)
    from lore.release import published_spec

    assert mcp_entry("cursor") == {
        "command": "uvx",
        "args": [
            "--managed-python",
            "--python",
            "3.12",
            "--no-build",
            published_spec(with_map=False),
            "mcp",
        ],
        "env": {"LORE_WORKSPACE": str(tmp_path)},
    }
    assert install_command() == "uvx lore-solo connect"
    assert windows_command("uvx lore-solo connect") == "uvx lore-solo connect"
    assert windows_command("scripts/lore-solo connect") == "scripts/lore-solo.ps1 connect"


def test_mcp_entry_is_a_local_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LORE_COMMAND", "/opt/lore/bin/lore")
    monkeypatch.setenv("LORE_WORKSPACE", str(tmp_path / "proj"))
    assert mcp_entry("cursor") == {
        "command": "/opt/lore/bin/lore",
        "args": ["mcp"],
        "env": {"LORE_WORKSPACE": str(tmp_path / "proj")},
    }
    vscode = mcp_entry("vscode", client="Cursor")
    assert vscode["command"] == "/opt/lore/bin/lore"
    assert vscode["args"] == ["mcp"]
    assert vscode["type"] == "stdio"
    assert vscode["env"] == {
        "LORE_CLIENT": "Cursor",
        "LORE_WORKSPACE": str(tmp_path / "proj"),
    }


def test_register_keeps_servers_already_in_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LORE_COMMAND", "lore")
    monkeypatch.setenv("LORE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr("lore.connect.Path.home", lambda: tmp_path)
    cursor = tmp_path / ".cursor" / "mcp.json"
    cursor.parent.mkdir()
    cursor.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"command": "other"},
                    "lore": {"command": "old-go-lore"},
                }
            }
        )
        + "\n",
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
    (tmp_path / ".gemini" / "config").mkdir(parents=True)
    (tmp_path / ".vscode").mkdir()

    result = register_agents(tmp_path, system="linux")

    saved = json.loads(cursor.read_text(encoding="utf-8"))
    assert saved["mcpServers"]["other"]["command"] == "other"
    assert "lore" not in saved["mcpServers"]
    assert saved["mcpServers"][MCP_SERVER_NAME]["command"] == "lore"
    assert saved["mcpServers"][MCP_SERVER_NAME]["args"] == ["mcp"]
    toml = (codex / "config.toml").read_text(encoding="utf-8")
    assert 'model = "keep"' in toml
    assert "[mcp_servers.other]" in toml
    assert f'[mcp_servers."{MCP_SERVER_NAME}"]' in toml
    assert 'command = "lore"' in toml
    assert 'args = ["mcp"]' in toml
    assert str(cursor) in result["written"]
    assert any(item.startswith("Claude Code:") for item in result["skipped"])
    assert not (tmp_path / ".config" / "Claude").exists()
    rule = (tmp_path / ".cursor" / "rules" / "lore.mdc").read_text(encoding="utf-8")
    assert "alwaysApply: true" in rule
    assert "get_context once" in rule
    assert "get_skill" in rule
    assert "Edit only those files" not in rule
    agents = (tmp_path / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    claude = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "get_context once" in agents
    assert "get_context once" in claude
    project_agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "check_applied" in project_agents
    anti = (tmp_path / ".agents" / "rules" / "lore.md").read_text(encoding="utf-8")
    assert "trigger: always_on" in anti
    copilot = (tmp_path / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "get_context once" in copilot


def test_upsert_rule_refreshes_the_managed_block_and_keeps_user_text(tmp_path: Path) -> None:
    from lore.connect import _upsert_rule
    from lore.core.instructions import RULE_BEGIN, RULE_END, STANDING_INSTRUCTIONS

    path = tmp_path / "AGENTS.md"
    path.write_text(
        "Team notes stay.\n\n"
        f"{RULE_BEGIN}\nold lore text\n{RULE_END}\n\n"
        "Trailing user notes.\n",
        encoding="utf-8",
    )
    _upsert_rule(path)
    text = path.read_text(encoding="utf-8")
    assert "Team notes stay." in text
    assert "Trailing user notes." in text
    assert "old lore text" not in text
    assert STANDING_INSTRUCTIONS in text
    assert text.count(RULE_BEGIN) == 1
    _upsert_rule(path)
    again = path.read_text(encoding="utf-8")
    assert again.count(RULE_BEGIN) == 1
    assert "Trailing user notes." in again

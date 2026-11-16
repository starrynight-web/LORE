"""Windows self-update must not replace a running tool Python in-place."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lore.install_cmd import (
    _REEXEC_ENV,
    handoff_via_uvx,
    is_windows_file_lock_error,
    running_from_tool_env,
    tool_install_root,
    windows_self_replace_blocked,
)


def test_running_from_tool_env_detects_prefix_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.install_cmd.prefix", lambda: tmp_path / ".lore")
    root = tool_install_root()
    python = root / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    assert running_from_tool_env(str(python)) is True
    assert running_from_tool_env(str(tmp_path / "other" / "python.exe")) is False


def test_windows_block_respects_reexec_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.install_cmd.os.name", "nt")
    monkeypatch.setattr("lore.install_cmd.running_from_tool_env", lambda: True)
    monkeypatch.delenv(_REEXEC_ENV, raising=False)
    assert windows_self_replace_blocked() is True
    monkeypatch.setenv(_REEXEC_ENV, "1")
    assert windows_self_replace_blocked() is False


def test_file_lock_error_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.install_cmd.os.name", "nt")
    assert is_windows_file_lock_error("failed: Access is denied. (os error 5)")
    assert is_windows_file_lock_error("Cannot remove Scripts directory")
    monkeypatch.setattr("lore.install_cmd.os.name", "posix")
    assert not is_windows_file_lock_error("Access is denied. (os error 5)")


def test_handoff_writes_cmd_and_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.install_cmd.prefix", lambda: tmp_path / ".lore")
    monkeypatch.setattr("lore.install_cmd.os.getpid", lambda: 4242)
    seen: dict[str, Any] = {}

    def fake_popen(cmd: list[str], **kwargs: object) -> object:
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("lore.install_cmd.subprocess.Popen", fake_popen)
    with pytest.raises(SystemExit) as exc:
        handoff_via_uvx("/uv", "update", ["--no-map"])
    assert exc.value.code == 0
    script = tmp_path / ".lore" / "bin" / "_lore_solo_update_handoff.cmd"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "LORE_UPDATE_VIA_UVX=1" in text
    assert "4242" in text
    assert "tool run" in text
    assert "lore-solo update --no-map" in text
    assert seen["cmd"][0] == "cmd.exe"

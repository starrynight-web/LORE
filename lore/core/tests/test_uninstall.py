"""Uninstall removes the lore-solo command and leaves the library alone."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from lore.__main__ import main
from lore.uninstall_cmd import remove_targets, run, runtime_targets, tool_uninstall_args


def test_uninstall_asks_uv_for_the_package_name() -> None:
    assert tool_uninstall_args("uv") == ["uv", "tool", "uninstall", "--quiet", "lore-solo"]


def test_windows_runtime_uses_exe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.uninstall_cmd.os.name", "nt")
    assert runtime_targets(tmp_path)[0] == tmp_path / "bin" / "lore-solo.exe"


def _layout(home: Path) -> None:
    (home / "bin").mkdir(parents=True)
    (home / "tools" / "lore-solo").mkdir(parents=True)
    (home / "tools" / "lore").mkdir()
    (home / "site").mkdir()
    (home / "setup.log").write_text("log", encoding="utf-8")
    (home / "bin" / "lore-solo").symlink_to(home / "tools" / "lore-solo")
    (home / "bin" / "lore").symlink_to(home / "tools" / "lore")
    (home / "lore.config.yaml").write_text("keep: true\n", encoding="utf-8")


def test_remove_targets_leaves_the_older_lore_command(tmp_path: Path) -> None:
    home = tmp_path / ".lore"
    _layout(home)
    remove_targets(runtime_targets(home))
    assert not (home / "bin" / "lore-solo").exists()
    assert not (home / "tools" / "lore-solo").exists()
    assert not (home / "site").exists()
    assert not (home / "setup.log").exists()
    assert (home / "bin" / "lore").is_symlink()
    assert (home / "tools" / "lore").is_dir()
    assert (home / "lore.config.yaml").is_file()


def test_run_reports_when_nothing_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("lore.uninstall_cmd.prefix", lambda: tmp_path / ".lore")
    monkeypatch.setattr("lore.uninstall_cmd.find_uv", lambda: "uv")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess([], 2, "", "error: `lore-solo` is not installed\n")

    monkeypatch.setattr("lore.uninstall_cmd.subprocess.run", fake_run)
    run()
    assert capsys.readouterr().out.strip() == "Lore Solo is not installed."


def test_run_keeps_personas_when_uv_removes_the_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / ".lore"
    library = tmp_path / "library" / "persona.md"
    library.parent.mkdir(parents=True)
    library.write_text("role", encoding="utf-8")
    (home / "site").mkdir(parents=True)
    monkeypatch.setattr("lore.uninstall_cmd.prefix", lambda: home)
    monkeypatch.setattr("lore.uninstall_cmd.find_uv", lambda: "uv")
    seen: dict[str, str] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        assert isinstance(env, dict)
        seen["tool"] = env["UV_TOOL_DIR"]
        seen["bin"] = env["UV_TOOL_BIN_DIR"]
        assert args[-1] == "lore-solo"
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("lore.uninstall_cmd.subprocess.run", fake_run)
    run()
    assert seen == {"tool": str(home / "tools"), "bin": str(home / "bin")}
    assert not (home / "site").exists()
    assert library.is_file()
    assert "Uninstalled" in capsys.readouterr().out


def test_main_routes_uninstall(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake(argv: list[str] | None) -> None:
        seen.append(list(argv or []))

    monkeypatch.setattr("lore.uninstall_cmd.run", fake)
    assert main(["uninstall"]) == 0
    assert seen == [[]]

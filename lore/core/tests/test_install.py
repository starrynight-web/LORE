"""The install command is the same shape on every operating system."""

from __future__ import annotations

from pathlib import Path

import pytest
from lore.__main__ import main
from lore.install_cmd import installed_binary, tool_install_args


def test_published_install_uses_the_package_name() -> None:
    assert tool_install_args("uv", None) == [
        "uv",
        "tool",
        "install",
        "--quiet",
        "--python",
        "3.12",
        "--force",
        "lore-solo",
    ]


def test_checkout_install_is_editable(tmp_path: Path) -> None:
    assert tool_install_args("uv", tmp_path)[-2:] == ["--editable", str(tmp_path)]


def test_windows_binary_uses_exe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.install_cmd.os.name", "nt")
    monkeypatch.setattr("lore.install_cmd.Path.home", lambda: tmp_path)
    assert installed_binary() == tmp_path / ".lore" / "bin" / "lore-solo.exe"


def test_main_routes_install(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake(argv: list[str] | None) -> None:
        seen.append(list(argv or []))

    monkeypatch.setattr("lore.install_cmd.run", fake)
    assert main(["install"]) == 0
    assert seen == [[]]

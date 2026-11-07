"""The install command is the same shape on every operating system."""

from __future__ import annotations

from pathlib import Path

import pytest
from lore.__main__ import main
from lore.install_cmd import (
    installed_binary,
    is_native_build_failure,
    parse_install_flags,
    tool_install_args,
)


def test_published_install_uses_the_map_extra_by_default() -> None:
    assert tool_install_args("uv", None) == [
        "uv",
        "tool",
        "install",
        "--quiet",
        "--python",
        "3.12",
        "--force",
        "lore-solo[map]",
    ]


def test_core_install_omits_the_map_extra() -> None:
    assert tool_install_args("uv", None, with_map=False)[-1] == "lore-solo"


def test_checkout_install_is_editable_with_map_extra(tmp_path: Path) -> None:
    assert tool_install_args("uv", tmp_path)[-4:] == [
        "--editable",
        str(tmp_path),
        "--extra",
        "map",
    ]


def test_checkout_core_install_skips_extra(tmp_path: Path) -> None:
    assert tool_install_args("uv", tmp_path, with_map=False)[-2:] == [
        "--editable",
        str(tmp_path),
    ]


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


def test_main_routes_map(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[Path] = []

    def fake(project: Path, status_path: Path | None = None) -> dict[str, str]:
        del status_path
        seen.append(project)
        return {"state": "running"}

    monkeypatch.setattr("lore.setup.graph_job.start_build", fake)
    monkeypatch.setattr("lore.core.paths.map_root", lambda start: start)
    assert main(["map", str(tmp_path)]) == 0
    assert seen == [tmp_path]


def test_parse_install_flags() -> None:
    assert parse_install_flags(["--map"]) == (True, [])
    assert parse_install_flags(["--no-map"]) == (False, [])
    assert parse_install_flags([]) == (None, [])


def test_native_build_failure_classifier() -> None:
    assert is_native_build_failure(
        "error: Microsoft Visual C++ 14.0 or greater is required.\n"
        "Failed to build tree-sitter==0.25.2"
    )
    assert is_native_build_failure("Failed building wheel for tree-sitter")
    assert not is_native_build_failure("error: package lore-solo not found")

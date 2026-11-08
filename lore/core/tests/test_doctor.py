"""Doctor reports missing tools with OS-specific install hints."""

from __future__ import annotations

from pathlib import Path

import pytest
from lore.__main__ import main
from lore.doctor_cmd import (
    check_editors,
    check_node,
    check_npm,
    check_uv,
    format_report,
    node_install_hint,
    run,
    uv_install_hint,
)


def test_uv_hint_differs_by_os() -> None:
    assert "install.ps1" in uv_install_hint("windows")
    assert "install.sh" in uv_install_hint("linux")
    assert "install.sh" in uv_install_hint("darwin")


def test_node_hint_mentions_winget_on_windows() -> None:
    assert "winget" in node_install_hint("windows")
    assert "brew" in node_install_hint("darwin")
    assert "nodejs.org" in node_install_hint("linux")


def test_check_uv_missing_explains_impact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.doctor_cmd.find_uv", lambda: None)
    row = check_uv("linux")
    assert row.ok is False
    assert row.required is True
    assert "uvx" in row.without_it
    assert "install.sh" in row.get_it


def test_check_uv_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.doctor_cmd.find_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr("lore.doctor_cmd._run_version", lambda _cmd: "uv 0.13.7")
    row = check_uv("linux", uv_path="/usr/bin/uv")
    assert row.ok is True
    assert "0.13.7" in row.detail


def test_check_node_rejects_old_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.doctor_cmd.shutil.which", lambda name: "/usr/bin/node" if name == "node" else None)
    monkeypatch.setattr("lore.doctor_cmd._run_version", lambda _cmd: "v16.20.0")
    row = check_node("linux")
    assert row.ok is False
    assert "18+" in row.detail
    assert "setup website" in row.without_it


def test_check_npm_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.doctor_cmd.shutil.which", lambda _name: None)
    row = check_npm("darwin")
    assert row.ok is False
    assert "npm ci" in row.without_it
    assert "brew" in row.get_it


def test_check_editors_none(tmp_path: Path) -> None:
    row = check_editors("linux", home=tmp_path)
    assert row.ok is False
    assert row.required is False
    assert "connect" in row.without_it


def test_check_editors_finds_cursor(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    row = check_editors("linux", home=tmp_path)
    assert row.ok is True
    assert "Cursor" in row.detail


def test_format_report_lists_required_failures() -> None:
    from lore.doctor_cmd import Check

    report = format_report(
        [
            Check("uv", "uv", False, True, "not found", "get uv", "no install"),
            Check("map", "map", False, False, "missing", "get map", "no map"),
        ],
        "linux",
    )
    assert "MISSING" in report
    assert "optional" in report
    assert "Without this: no install" in report
    assert "Fix required tools first: uv" in report


def test_run_returns_1_when_required_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from lore.doctor_cmd import Check

    monkeypatch.setattr(
        "lore.doctor_cmd.gather_checks",
        lambda _system: [
            Check("uv", "uv", False, True, "not found", "install uv", "blocked"),
        ],
    )
    assert run([]) == 1


def test_run_returns_0_when_only_optional_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from lore.doctor_cmd import Check

    monkeypatch.setattr(
        "lore.doctor_cmd.gather_checks",
        lambda _system: [
            Check("uv", "uv", True, True, "ok", "", ""),
            Check("map", "map", False, False, "missing", "install map", "no map"),
        ],
    )
    assert run([]) == 0


def test_main_routes_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake(argv: list[str] | None) -> int:
        seen.append(list(argv or []))
        return 0

    monkeypatch.setattr("lore.doctor_cmd.run", fake)
    assert main(["doctor"]) == 0
    assert seen == [[]]

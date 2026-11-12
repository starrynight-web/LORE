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


def test_node_hint_targets_node_22() -> None:
    assert "latest-v22.x" in node_install_hint("windows")
    assert "node@22" in node_install_hint("darwin")
    assert "latest-v22.x" in node_install_hint("linux")


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
    assert "22+" in row.detail
    assert "setup website" in row.without_it


def test_check_node_rejects_garbage_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.doctor_cmd.shutil.which", lambda name: "/usr/bin/node" if name == "node" else None)
    monkeypatch.setattr("lore.doctor_cmd._run_version", lambda _cmd: "not-a-version")
    row = check_node("linux")
    assert row.ok is False


def test_check_npm_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.doctor_cmd.shutil.which", lambda _name: None)
    row = check_npm("darwin")
    assert row.ok is False
    assert "source checkout" in row.without_it
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
        lambda _system, **_kw: [
            Check("uv", "uv", False, True, "not found", "install uv", "blocked"),
        ],
    )
    assert run([]) == 1


def test_run_returns_0_when_only_optional_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from lore.doctor_cmd import Check

    monkeypatch.setattr(
        "lore.doctor_cmd.gather_checks",
        lambda _system, **_kw: [
            Check("uv", "uv", True, True, "ok", "", ""),
            Check("map", "map", False, False, "missing", "install map", "no map"),
        ],
    )
    assert run([]) == 0


def test_check_python_reports_implementation_and_arch() -> None:
    from lore.doctor_cmd import check_python

    row = check_python()
    assert row.ok is True
    assert row.required is True
    assert "Python" in row.detail or "PyPy" in row.detail or "CPython" in row.detail
    assert "3." in row.detail


def test_core_gather_makes_node_optional() -> None:
    from lore.doctor_cmd import gather_checks

    checks = {check.id: check for check in gather_checks("linux")}
    assert checks["node"].required is False
    assert checks["npm"].required is False
    assert checks["map"].required is False
    assert checks["python"].required is True
    assert checks["uv"].required is True


def test_setup_gather_requires_node_22_not_npm() -> None:
    from lore.doctor_cmd import gather_checks

    checks = {check.id: check for check in gather_checks("linux", for_setup=True)}
    assert checks["node"].required is True
    assert checks["npm"].required is False
    assert "uv" not in checks
    assert "map" not in checks


def test_setup_gather_flags_node_21(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "lore.doctor_cmd.shutil.which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )
    monkeypatch.setattr("lore.doctor_cmd._run_version", lambda _cmd: "v21.7.3")
    from lore.doctor_cmd import check_node

    row = check_node("linux", required=True, minimum=22)
    assert row.ok is False
    assert "22+" in row.detail


def test_run_setup_mode_uses_setup_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    from lore.doctor_cmd import Check

    seen: dict[str, bool] = {}

    def fake_gather(_system: str, *, for_setup: bool = False) -> list[Check]:
        seen["for_setup"] = for_setup
        return [Check("node", "Node.js", True, True, "v22", "", "")]

    monkeypatch.setattr("lore.doctor_cmd.gather_checks", fake_gather)
    assert run(["--setup"]) == 0
    assert seen["for_setup"] is True


def test_node_check_core_minimum_is_22(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "lore.doctor_cmd.shutil.which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )
    monkeypatch.setattr("lore.doctor_cmd._run_version", lambda _cmd: "v18.20.0")
    from lore.doctor_cmd import check_node

    row = check_node("linux", required=False)
    assert row.ok is False
    assert "22+" in row.detail


def test_main_routes_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake(argv: list[str] | None) -> int:
        seen.append(list(argv or []))
        return 0

    monkeypatch.setattr("lore.doctor_cmd.run", fake)
    assert main(["doctor"]) == 0
    assert seen == [[]]

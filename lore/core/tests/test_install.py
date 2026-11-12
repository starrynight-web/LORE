"""The install command is the same shape on every operating system."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from lore.__main__ import main
from lore.install_cmd import (
    installed_binary,
    is_map_unavailable,
    is_native_build_failure,
    parse_install_flags,
    sanitize_output,
    tool_install_args,
)
from lore.release import release_version


def test_published_install_uses_the_map_extra_by_default() -> None:
    constraints = Path("/tmp/constraints.txt")
    args = tool_install_args("uv", None, constraints=constraints)
    assert args[:10] == [
        "uv",
        "tool",
        "install",
        "--quiet",
        "--managed-python",
        "--python",
        "3.12",
        "--no-build",
        "--force",
        "-c",
    ]
    assert args[10] == str(constraints)
    assert args[-1] == f"lore-solo[map]=={release_version()}"


def test_core_install_omits_the_map_extra() -> None:
    args = tool_install_args("uv", None, with_map=False, constraints=Path("/c.txt"))
    assert args[-1] == f"lore-solo=={release_version()}"
    assert "--extra" not in args


def test_checkout_install_is_editable_with_map_extra(tmp_path: Path) -> None:
    args = tool_install_args("uv", tmp_path, constraints=Path("/c.txt"))
    assert args[-2:] == ["--editable", f"{tmp_path}[map]"]
    assert "--extra" not in args


def test_checkout_core_install_skips_extra(tmp_path: Path) -> None:
    args = tool_install_args("uv", tmp_path, with_map=False, constraints=Path("/c.txt"))
    assert args[-2:] == ["--editable", str(tmp_path)]
    assert "--extra" not in args
    assert "[map]" not in args[-1]


def test_install_without_constraints_resource() -> None:
    args = tool_install_args("uv", None)
    if "-c" in args:
        index = args.index("-c")
        assert args[index + 1].endswith("release_constraints.txt")
    assert args[-1] == f"lore-solo[map]=={release_version()}"


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

    def fake(
        project: Path, status_path: Path | None = None, *, force: bool = False
    ) -> dict[str, str]:
        del status_path, force
        seen.append(project)
        return {"state": "ready"}

    monkeypatch.setattr("lore.setup.graph_job.start_build", fake)
    monkeypatch.setattr("lore.core.paths.map_root", lambda start: start)
    assert main(["map", str(tmp_path)]) == 0
    assert seen == [tmp_path]


def test_parse_install_flags() -> None:
    assert parse_install_flags(["--map"]) == (True, [])
    assert parse_install_flags(["--no-map"]) == (False, [])
    assert parse_install_flags([]) == (None, [])


def test_parse_install_flags_rejects_conflicts() -> None:
    with pytest.raises(SystemExit, match="conflicting"):
        parse_install_flags(["--map", "--no-map"])
    with pytest.raises(SystemExit, match="conflicting"):
        parse_install_flags(["--no-map", "--map"])


def test_native_build_failure_classifier() -> None:
    assert is_native_build_failure(
        "error: Microsoft Visual C++ 14.0 or greater is required.\n"
        "Failed to build tree-sitter==0.25.2"
    )
    assert is_native_build_failure("Failed building wheel for tree-sitter")
    assert not is_native_build_failure("error: package lore-solo not found")


def test_map_unavailable_needs_a_map_dependency_miss() -> None:
    assert is_map_unavailable(
        "no solution found when resolving dependencies: graphifyy==0.9.93"
    )
    assert is_map_unavailable(
        "no compatible wheel found for tree-sitter on this platform"
    )
    assert not is_map_unavailable("no matching distribution found for django")
    assert not is_map_unavailable("connection refused to pypi.org")


def test_sanitize_output_redacts_credentials_and_tokens() -> None:
    text = (
        "GET https://user:s3cret@pypi.example/simple/graphifyy/ "
        "Authorization: Bearer abc123TOKEN api_key=sk-live-999"
    )
    cleaned = sanitize_output(text)
    assert "s3cret" not in cleaned
    assert "abc123TOKEN" not in cleaned
    assert "sk-live-999" not in cleaned
    assert "https://***@pypi.example" in cleaned


def _fake_proc(code: int, err: str = "", out: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stderr=err, stdout=out)


def _install_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr("lore.install_cmd.find_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr("lore.install_cmd.checkout_root", lambda: None)
    monkeypatch.setattr(
        "lore.install_cmd.packaged_constraints", lambda: tmp_path / "c.txt"
    )

    def fake_run(
        uv: str,
        checkout: Path | None,
        *,
        with_map: bool,
        constraints: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(["map" if with_map else "core"])
        return _fake_proc(0)

    monkeypatch.setattr("lore.install_cmd._run_uv", fake_run)
    return calls


def test_strict_map_failure_never_claims_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _install_env(monkeypatch, tmp_path)

    def fail(
        uv: str, checkout: Path | None, *, with_map: bool, constraints: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        calls.append(["map"])
        return _fake_proc(1, err="no compatible wheel for tree-sitter")

    monkeypatch.setattr("lore.install_cmd._run_uv", fail)
    from lore.install_cmd import run

    with pytest.raises(SystemExit):
        run(["--map"])
    captured = capsys.readouterr()
    assert "Installed" not in captured.out
    assert "--no-map" in captured.err
    assert calls == [["map"]]


def test_default_falls_back_to_core_only_on_map_miss(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _install_env(monkeypatch, tmp_path)
    responses = {
        True: _fake_proc(1, err="no compatible wheel found for graphifyy"),
        False: _fake_proc(0),
    }

    def fake_run(
        uv: str, checkout: Path | None, *, with_map: bool, constraints: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        calls.append(["map" if with_map else "core"])
        return responses[with_map]

    monkeypatch.setattr("lore.install_cmd._run_uv", fake_run)
    from lore.install_cmd import run

    run([])
    out = capsys.readouterr().out
    assert "without the codebase map" in out
    assert calls == [["map"], ["core"]]


def test_default_does_not_fall_back_on_network_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _install_env(monkeypatch, tmp_path)

    def fake_run(
        uv: str, checkout: Path | None, *, with_map: bool, constraints: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        calls.append(["map" if with_map else "core"])
        return _fake_proc(1, err="error: connection refused to pypi.org")

    monkeypatch.setattr("lore.install_cmd._run_uv", fake_run)
    from lore.install_cmd import run

    with pytest.raises(SystemExit):
        run([])
    assert calls == [["map"]]


def test_default_fallback_core_failure_aborts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _install_env(monkeypatch, tmp_path)

    def fake_run(
        uv: str, checkout: Path | None, *, with_map: bool, constraints: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        calls.append(["map" if with_map else "core"])
        if with_map:
            return _fake_proc(1, err="no compatible wheel found for graphifyy")
        return _fake_proc(2, err="boom")

    monkeypatch.setattr("lore.install_cmd._run_uv", fake_run)
    from lore.install_cmd import run

    with pytest.raises(SystemExit):
        run([])
    assert calls == [["map"], ["core"]]


def test_run_rejects_flag_conflict() -> None:
    from lore.install_cmd import run

    with pytest.raises(SystemExit, match="conflicting"):
        run(["--map", "--no-map"])


def test_install_aborts_without_constraints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _install_env(monkeypatch, tmp_path)
    monkeypatch.setattr("lore.install_cmd.packaged_constraints", lambda: None)
    from lore.install_cmd import run

    with pytest.raises(SystemExit, match="constraints"):
        run([])
    assert calls == []


def test_strict_map_network_failure_is_truthful(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _install_env(monkeypatch, tmp_path)

    def fail(
        uv: str, checkout: Path | None, *, with_map: bool, constraints: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        calls.append(["map"])
        return _fake_proc(1, err="error: connection refused to pypi.org")

    monkeypatch.setattr("lore.install_cmd._run_uv", fail)
    from lore.install_cmd import run

    with pytest.raises(SystemExit):
        run(["--map"])
    err = capsys.readouterr().err
    assert "--no-map" not in err
    assert "no prebuilt" not in err

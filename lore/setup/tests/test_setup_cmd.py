"""Setup-site resolution, readiness, and child-process cleanup."""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from lore import setup_cmd
from lore.site_bundle import SiteError


class _Proc:
    def __init__(self, code: int | None = None) -> None:
        self.code = code
        self.pid = 99999
        self.terminated = False
        self.killed = False
        self.wait_raises: int = 0

    def poll(self) -> int | None:
        return self.code

    def terminate(self) -> None:
        self.terminated = True
        self.code = -15

    def wait(self, timeout: float | None = None) -> int:
        if self.wait_raises:
            self.wait_raises -= 1
            raise subprocess.TimeoutExpired("x", timeout or 0)
        return self.code if self.code is not None else -15

    def kill(self) -> None:
        self.killed = True
        self.code = -9


@pytest.fixture(autouse=True)
def _posix_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "nt":
        return

    def fake_killpg(pid: int, sig: int) -> None:
        raise ProcessLookupError(pid)

    monkeypatch.setattr(os, "killpg", fake_killpg)


def _bundle(tmp_path: Path) -> Path:
    archive = tmp_path / "site.zip"
    inner = {
        "schema_version": 1,
        "lore_version": __import__("lore").__version__,
        "platform": "linux-amd64",
        "build_id": "a" * 64,
        "node_major": 22,
    }
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("server.js", "// server")
        zf.writestr("site-manifest.json", json.dumps(inner))
    return archive


def test_resolve_site_env_dir_with_standalone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "web"
    (root / ".next" / "standalone").mkdir(parents=True)
    (root / ".next" / "standalone" / "server.js").write_text("//")
    monkeypatch.setenv("LORE_WEB_DIR", str(root))
    site = setup_cmd._resolve_site(None, False)
    assert site.server == root / ".next" / "standalone" / "server.js"


def test_resolve_site_env_dir_source_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "web"
    root.mkdir()
    (root / "package.json").write_text("{}")
    monkeypatch.setenv("LORE_WEB_DIR", str(root))
    site = setup_cmd._resolve_site(None, False)
    assert site.dev_dir == root


def test_resolve_site_env_dir_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "web"
    root.mkdir()
    monkeypatch.setenv("LORE_WEB_DIR", str(root))
    with pytest.raises(SiteError, match="LORE_WEB_DIR"):
        setup_cmd._resolve_site(None, False)


def test_resolve_site_uses_explicit_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LORE_WEB_DIR", raising=False)
    archive = _bundle(tmp_path)
    seen: dict[str, object] = {}

    def fake_ensure(**kwargs: object) -> object:
        seen.update(kwargs)
        server = tmp_path / "built" / "server.js"
        server.parent.mkdir()
        server.write_text("//")
        from lore.site_bundle import SiteResolution

        return SiteResolution(server=server, note="local")

    monkeypatch.setattr(setup_cmd, "ensure_site", fake_ensure)
    site = setup_cmd._resolve_site(archive, True)
    assert site.server is not None
    assert site.server.name == "server.js"
    assert site.note == "local"
    assert seen["site_bundle"] == archive
    assert seen["offline"] is True


def test_resolve_site_published_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LORE_WEB_DIR", raising=False)
    monkeypatch.setattr(setup_cmd, "_web_dir", lambda: tmp_path / "nope")

    def fake_ensure(**kwargs: object) -> object:
        from lore.site_bundle import SiteResolution

        assert kwargs["offline"] is False
        server = tmp_path / "dl" / "server.js"
        server.parent.mkdir()
        server.write_text("//")
        return SiteResolution(server=server)

    monkeypatch.setattr(setup_cmd, "ensure_site", fake_ensure)
    site = setup_cmd._resolve_site(None, False)
    assert site.server is not None


def test_resolve_site_checkout_standalone_with_current_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LORE_WEB_DIR", raising=False)
    web = tmp_path / "web"
    server = web / ".next" / "standalone" / "server.js"
    server.parent.mkdir(parents=True)
    server.write_text("//")
    (web / "package.json").write_text("{}")
    monkeypatch.setattr(setup_cmd, "_web_dir", lambda: web)
    monkeypatch.setattr(setup_cmd, "_standalone_current", lambda w, s: True)
    site = setup_cmd._resolve_site(None, False)
    assert site.server == server


def test_resolve_site_stale_standalone_falls_to_dev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LORE_WEB_DIR", raising=False)
    web = tmp_path / "web"
    server = web / ".next" / "standalone" / "server.js"
    server.parent.mkdir(parents=True)
    server.write_text("//")
    (web / "package.json").write_text("{}")
    monkeypatch.setattr(setup_cmd, "_web_dir", lambda: web)
    monkeypatch.setattr(setup_cmd, "_standalone_current", lambda w, s: False)
    site = setup_cmd._resolve_site(None, False)
    assert site.dev_dir == web
    assert site.server is None


def test_resolve_site_missing_everywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LORE_WEB_DIR", raising=False)
    monkeypatch.setattr(setup_cmd, "_web_dir", lambda: tmp_path / "nope")

    def fail(**_kw: object) -> object:
        raise SiteError("no published setup site")

    monkeypatch.setattr(setup_cmd, "ensure_site", fail)
    with pytest.raises(SiteError, match="no published"):
        setup_cmd._resolve_site(None, False)


def _procs(*procs: _Proc) -> list[subprocess.Popen[bytes]]:
    return [cast(subprocess.Popen[bytes], p) for p in procs]


def _probe_map(
    responses: dict[str, int | None],
) -> Callable[[str, str], bool]:
    ordered = sorted(responses.items(), key=lambda kv: -len(kv[0]))

    def fake(url: str, key: str) -> bool:
        for prefix, value in ordered:
            if url.startswith(prefix):
                return value == 200
        return False

    return fake


def test_wait_ready_reports_early_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_cmd, "_probe", lambda _u, _k: False)
    with pytest.raises(SiteError, match="exited"):
        setup_cmd._wait_ready(3000, 7421, "k", _procs(_Proc(code=1)), timeout=5)


def test_wait_ready_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_cmd, "_probe", lambda _u, _k: False)
    with pytest.raises(SiteError, match="ready"):
        setup_cmd._wait_ready(9, 7421, "k", _procs(_Proc()), timeout=0.2)


def test_wait_ready_needs_all_three_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake(url: str, key: str) -> bool:
        calls.append((url, key))
        return True

    monkeypatch.setattr(setup_cmd, "_probe", fake)
    setup_cmd._wait_ready(3000, 7421, "sekret", _procs(_Proc()))
    urls = [u for u, _ in calls]
    assert "http://127.0.0.1:3000/" in urls
    api = [u for u in urls if ":7421/api/browse" in u]
    proxy = [u for u in urls if ":3000/api/browse" in u]
    assert api and proxy
    keyed = [k for u, k in calls if "/api/browse" in u]
    assert keyed and all(k == "sekret" for k in keyed)


def test_wait_ready_http_500_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: dict[str, int | None] = {
        "http://127.0.0.1:3000/": 200,
        "http://127.0.0.1:7421/": 200,
        "http://127.0.0.1:3000/api": 500,
    }
    monkeypatch.setattr(setup_cmd, "_probe", _probe_map(responses))
    with pytest.raises(SiteError, match="ready"):
        setup_cmd._wait_ready(3000, 7421, "k", _procs(_Proc()), timeout=0.5)


def test_wait_ready_foreign_service_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: dict[str, int | None] = {
        "http://127.0.0.1:3000/": 200,
        "http://127.0.0.1:7421/api": 401,
        "http://127.0.0.1:3000/api": 401,
    }
    monkeypatch.setattr(setup_cmd, "_probe", _probe_map(responses))
    with pytest.raises(SiteError, match="ready"):
        setup_cmd._wait_ready(3000, 7421, "k", _procs(_Proc()), timeout=0.5)


def test_stop_terminates_then_kills_stubborn() -> None:
    stubborn = _Proc()
    stubborn.wait_raises = 10
    setup_cmd._stop(_procs(stubborn))
    assert stubborn.terminated is True
    assert stubborn.killed is True


def test_banner_prints_after_readiness(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    proc = _Proc()
    order: list[str] = []

    def fake_start(key: str, **kwargs: object) -> list[_Proc]:
        order.append("start")
        return [proc]

    def fake_ready(*a: object, **kw: object) -> None:
        order.append("ready")
        proc.code = 0

    monkeypatch.setattr(setup_cmd, "start_processes", fake_start)
    monkeypatch.setattr(setup_cmd, "_wait_ready", fake_ready)
    monkeypatch.setattr(setup_cmd, "_resolve_site", lambda _b, _o: setup_cmd._Site())
    monkeypatch.setenv("LORE_SETUP_KEY", "k3y")
    monkeypatch.delenv("LORE_WEB_PORT", raising=False)
    with pytest.raises(SystemExit):
        setup_cmd.run([])
    out = capsys.readouterr().out
    assert "http://127.0.0.1:3000/?key=k3y" in out
    assert order == ["start", "ready"]


def test_child_exit_zero_is_unexpected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    proc = _Proc()
    monkeypatch.setattr(setup_cmd, "start_processes", lambda _k, **_kw: [proc])
    monkeypatch.setattr(
        setup_cmd, "_wait_ready", lambda *a, **kw: setattr(proc, "code", 0)
    )
    monkeypatch.setattr(setup_cmd, "_resolve_site", lambda _b, _o: setup_cmd._Site())
    monkeypatch.setenv("LORE_SETUP_KEY", "k")
    with pytest.raises(SystemExit) as exc:
        setup_cmd.run([])
    assert exc.value.code != 0
    assert "unexpectedly" in str(exc.value)


def test_ctrlc_during_readiness_still_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _Proc()
    monkeypatch.setattr(setup_cmd, "start_processes", lambda _k, **_kw: [proc])

    def interrupt(*a: object, **kw: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(setup_cmd, "_wait_ready", interrupt)
    monkeypatch.setattr(setup_cmd, "_resolve_site", lambda _b, _o: setup_cmd._Site())
    monkeypatch.setenv("LORE_SETUP_KEY", "k")
    setup_cmd.run([])
    assert proc.terminated is True or proc.killed is True


def test_site_error_becomes_clean_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_b: object, _o: object) -> setup_cmd._Site:
        raise SiteError("no published setup site for linux-amd64")

    monkeypatch.setattr(setup_cmd, "_resolve_site", fail)
    with pytest.raises(SystemExit, match="no published"):
        setup_cmd.run([])


def test_require_node_reports_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_cmd, "node_runtime", lambda: "/usr/bin/node")
    assert setup_cmd._require_node() == "/usr/bin/node"


def test_require_node_missing_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_cmd, "node_runtime", lambda: None)
    with pytest.raises(SiteError, match="Node 22"):
        setup_cmd._require_node()


def test_web_spawn_failure_stops_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    api = _Proc()
    monkeypatch.setattr(setup_cmd, "_require_node", lambda: "/usr/bin/node")
    log_path = tmp_path / "setup.log"
    monkeypatch.setattr(
        setup_cmd, "_setup_log", lambda: log_path.open("wb")
    )
    monkeypatch.setattr(
        setup_cmd, "npm_command", lambda *args: ["npm", *args]
    )
    spawned: list[list[str]] = []

    def fake_spawn(command: list[str], **kw: object) -> _Proc:
        spawned.append(command)
        if len(spawned) == 1:
            return api
        raise OSError("spawn failed")

    monkeypatch.setattr(setup_cmd, "_spawn", fake_spawn)
    with pytest.raises(OSError, match="spawn failed"):
        setup_cmd.start_processes("k", site=setup_cmd._Site(dev_dir=tmp_path))
    assert api.terminated is True or api.killed is True


def test_offline_flag_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        setup_cmd,
        "_resolve_site",
        lambda bundle, offline: seen.update(bundle=bundle, offline=offline) or setup_cmd._Site(),
    )
    monkeypatch.setattr(setup_cmd, "start_processes", lambda _k, **_kw: [])
    monkeypatch.setenv("LORE_SETUP_KEY", "k")
    setup_cmd.run(["--offline", "--site-bundle", "/tmp/x.zip"])
    assert seen["offline"] is True
    assert seen["bundle"] == Path("/tmp/x.zip")


def test_web_port_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        setup_cmd,
        "start_processes",
        lambda _k, **kw: seen.update(kw) or [],
    )
    monkeypatch.setattr(setup_cmd, "_resolve_site", lambda _b, _o: setup_cmd._Site())
    monkeypatch.setenv("LORE_SETUP_KEY", "k")
    monkeypatch.setenv("LORE_WEB_PORT", "4100")
    setup_cmd.run([])
    assert seen["port"] == 4100


def test_web_port_rejects_bad_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_WEB_PORT", "banana")
    with pytest.raises(SystemExit, match="LORE_WEB_PORT"):
        setup_cmd.run([])


def test_web_port_rejects_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_WEB_PORT", "70000")
    with pytest.raises(SystemExit, match="65535"):
        setup_cmd.run([])

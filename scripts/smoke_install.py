#!/usr/bin/env python3
"""Install the built wheel into an isolated environment and exercise it.

CI/release helper: creates a fresh managed-Python 3.12 venv via uv (required;
no fallbacks), installs exactly one wheel from --artifacts with binary-only
third-party deps pinned by the constraints extracted from that wheel, and
drives a real MCP stdio conversation against fixture content. `--mode full`
also maps a tiny fixture with real Graphify and starts the setup site from a
pinned, platform-matched local bundle in --offline mode.

Never installs editable, never uses PYTHONPATH, never touches the user's
real HOME or cache/config directories.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []
EVIDENCE: dict[str, Any] = {"checks": []}

API_PORT = 7421

_OFFLINE_PROBE = '''
import json, socket, sys, unittest.mock
from pathlib import Path

real_connect = socket.socket.connect
def guarded(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        raise OSError("network disabled for smoke")
    return real_connect(self, address)

with unittest.mock.patch.object(socket.socket, "connect", guarded):
    from lore.core.context import get_context as build_context
    result = build_context(Path(sys.argv[1]), "", "react component state", "")
    items = result.get("items") or []
    out = {
        "verdict": result.get("verdict"),
        "items": len(items),
        "summary": bool(str(result.get("summary") or "").strip()),
    }
    sys.stdout.write(json.dumps(out))
'''


def check(name: str, ok: bool, detail: str = "") -> None:
    EVIDENCE["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        FAILURES.append(name)


def _run(command: list[str], env: dict[str, str] | None = None, **kw: Any) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, env=env, capture_output=True, check=False, **kw)


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        print("uv is required for the managed-Python 3.12 smoke install", file=sys.stderr)
        raise SystemExit(2)
    return uv


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _port_busy(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def isolated_env(home: Path, workspace: Path, library: Path) -> dict[str, str]:
    """Every user-writable location points inside the fixture."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "LORE_WORKSPACE": str(workspace),
        "LORE_LIBRARY": str(library),
        "LORE_CLIENT": "smoke",
    }
    for key in ("SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP", "TMP"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def make_venv(root: Path, env: dict[str, str]) -> Path:
    uv = _uv()
    result = _run(
        [uv, "venv", "--managed-python", "--python", "3.12", str(root)],
        env=env,
    )
    if result.returncode != 0 or not _venv_python(root).is_file():
        print(
            "uv could not create a managed Python 3.12 venv: "
            + result.stderr.decode("utf-8", "replace")[-300:],
            file=sys.stderr,
        )
        raise SystemExit(2)
    return root


def wheel_constraints(wheel: Path, dest: Path) -> Path:
    with zipfile.ZipFile(wheel) as zf:
        data = zf.read("lore/release_constraints.txt")
    out = dest / "wheel-constraints.txt"
    out.write_bytes(data)
    return out


def install_wheel(
    venv: Path, wheel: Path, constraints: Path, with_map: bool, env: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    requirement = f"{wheel}[map]" if with_map else str(wheel)
    return _run(
        [
            _uv(),
            "pip",
            "install",
            "--python",
            str(_venv_python(venv)),
            "--only-binary=:all:",
            "-c",
            str(constraints),
            requirement,
        ],
        env=env,
    )


def make_fixture(workspace: Path, library: Path) -> None:
    """Approved persona/skill content only, in the shared library.

    The workspace stays bare so the run proves the library store is used;
    no decisions, provider files, config, or history are copied.
    """
    workspace.mkdir(parents=True)
    store = library / ".lore"
    pack = REPO / "examples" / "persona-pack" / ".lore"
    for kind in ("personas", "skills"):
        source = pack / kind
        if source.is_dir():
            shutil.copytree(source, store / kind)


async def mcp_roundtrip(python: Path, env: dict[str, str]) -> dict[str, Any]:
    from fastmcp import Client

    config = {
        "mcpServers": {
            "lore": {
                "command": str(python),
                "args": ["-m", "lore", "mcp"],
                "env": env,
                "cwd": env["LORE_WORKSPACE"],
            }
        }
    }
    seen: dict[str, Any] = {}
    async with Client(config) as client:
        context = await client.call_tool(
            "get_context",
            {
                "intent": "react component state handling",
                "file_path": "src/App.tsx",
            },
        )
        seen["context"] = context.data
        cite_ids = list((seen["context"].get("data") or {}).get("cite_ids") or [])
        skill = await client.call_tool(
            "get_skill", {"name": "frontend-engineer/react-practices@v1"}
        )
        seen["skill"] = skill.data
        decision_id = str(seen["context"].get("decision_id", ""))
        applied = await client.call_tool(
            "check_applied",
            {"decision_id": decision_id, "rule_ids": cite_ids},
        )
        seen["applied"] = applied.data
        logged = await client.call_tool(
            "log_decision",
            {"decision_id": decision_id, "outcome": "applied"},
        )
        seen["logged"] = logged.data
        mapped = await client.call_tool("map_codebase", {})
        seen["map"] = mapped.data
    return seen


def _mcp_checks(python: Path, env: dict[str, str]) -> None:
    rehearsal = dict(env)
    rehearsal["LORE_MAP_ENABLED"] = "0"
    try:
        seen = asyncio.run(mcp_roundtrip(python, rehearsal))
    except Exception as exc:  # noqa: BLE001 - smoke must report, not traceback
        check("mcp stdio round trip", False, str(exc)[:300])
        return
    context = seen.get("context") or {}
    check("get_context decision receipt", bool(context.get("decision_id")))
    check(
        "get_context verdict ok",
        str(context.get("verdict")) == "ok",
        str(context.get("verdict")),
    )
    cite_ids = list((context.get("data") or {}).get("cite_ids") or [])
    check(
        "served cite_ids nonempty",
        bool(cite_ids) and all(str(c).startswith("skill:") for c in cite_ids),
        ",".join(cite_ids)[:200],
    )
    skill = seen.get("skill") or {}
    check(
        "get_skill full body",
        "function components" in str(skill.get("body", "")),
        str(skill.get("id")),
    )
    check("get_skill body hash", bool(skill.get("body_sha256")))
    skill_id = str(skill.get("id") or "")
    served = {str(c).removeprefix("skill:") for c in cite_ids}
    check(
        "cite_ids match full skill",
        bool(cite_ids) and skill_id.removeprefix("skill:") in served,
        skill_id,
    )
    applied = seen.get("applied") or {}
    check(
        "check_applied citation receipt",
        applied.get("check_kind") == "citation_receipt",
        str(applied.get("check_kind")),
    )
    check(
        "check_applied not code verified",
        applied.get("code_verified") is False,
        str(applied.get("code_verified")),
    )
    check(
        "check_applied status pass",
        str(applied.get("status")) == "pass",
        str(applied.get("status")),
    )
    logged = seen.get("logged") or {}
    check(
        "log_decision recorded",
        str(logged.get("status")) == "recorded",
        str(logged.get("status")),
    )
    mapped = seen.get("map") or {}
    check(
        "map disabled by LORE_MAP_ENABLED=0",
        str(mapped.get("state")) in {"unavailable", "missing"},
        str(mapped.get("state")),
    )


def _wheel_contents(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as zf:
        return zf.namelist()


def _wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as zf:
        meta_name = next(
            (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")), None
        )
        if meta_name is None:
            return ""
        for line in zf.read(meta_name).decode("utf-8", "replace").splitlines():
            if line.startswith("Version:"):
                return line.split(":", 1)[1].strip()
    return ""


def _probe(url: str, key: str = "") -> int:
    for attempt in range(10):
        request = urllib.request.Request(url)
        if key:
            request.add_header("X-Lore-Key", key)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return int(response.status)
        except urllib.error.HTTPError as exc:
            return int(exc.code)
        except (urllib.error.URLError, OSError):
            if attempt == 9:
                return 0
            time.sleep(0.5)
    return 0


def _read_until(
    process: subprocess.Popen[str], marker: str, timeout: float
) -> tuple[str, list[str]]:
    """Read child stdout until `marker`, with a real deadline."""
    lines: list[str] = []
    found = ""
    out: queue.Queue[str | None] = queue.Queue()
    stream = process.stdout

    def pump() -> None:
        try:
            if stream is not None:
                for line in stream:
                    out.put(line)
        finally:
            out.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = out.get(timeout=0.2)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if line is None:
            break
        lines.append(line)
        if marker in line:
            found = line
            break
    return found, lines


def _setup_smoke(
    python: Path, env: dict[str, str], bundle: Path, port: int, artifacts: Path
) -> None:
    creation = 0
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        kwargs["creationflags"] = creation
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(
        [
            str(python),
            "-m",
            "lore",
            "setup",
            "--site-bundle",
            str(bundle),
            "--offline",
            "--port",
            str(port),
        ],
        env=env,
        cwd=env["LORE_WORKSPACE"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **kwargs,
    )
    log_path = artifacts / "smoke-setup.log"
    key = ""
    lines: list[str] = []
    try:
        banner, lines = _read_until(process, "?key=", 90)
        if banner:
            key = banner.split("?key=", 1)[-1].strip()
        check(
            "setup banner with key",
            bool(key),
            lines[-1].strip()[:200] if lines else "no output",
        )
        if not key:
            return
        check("setup root page", _probe(f"http://127.0.0.1:{port}/") == 200)
        browse = urllib.parse.quote(env["LORE_WORKSPACE"])
        check(
            "setup api unkeyed 401",
            _probe(f"http://127.0.0.1:{port}/api/browse?path={browse}") == 401,
        )
        check(
            "setup api keyed 200",
            _probe(f"http://127.0.0.1:{port}/api/browse?path={browse}", key) == 200,
        )
        check(
            "setup direct api keyed 200",
            _probe(
                f"http://127.0.0.1:{API_PORT}/api/browse?path={browse}", key
            )
            == 200,
        )
    finally:
        if process.poll() is None:
            if os.name == "nt":
                process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
            else:
                process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        check("setup clean shutdown", process.returncode in {0, 130}, str(process.returncode))
        _drain, extra = _read_until(process, "\x00never", 2)
        lines.extend(extra)
        log_path.write_text("".join(lines), encoding="utf-8")
        check(
            "setup ports closed",
            _port_closed(port) and _port_closed(API_PORT),
            f"web={port} api={API_PORT}",
        )
        orphans = _fixture_processes(Path(str(env["HOME"])).parent)
        if orphans is None:
            EVIDENCE.setdefault("limitations", []).append(
                f"process audit not performed on {os.name}: pgrep unavailable"
            )
        else:
            check("no setup orphans", not orphans, ",".join(orphans[:5]))


def _port_closed(port: int, deadline: float = 5.0) -> bool:
    """True once nothing listens on 127.0.0.1:port; bounded wait."""
    end = time.monotonic() + deadline
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                pass
        except OSError:
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.3)


def _fixture_processes(root: str | Path) -> list[str] | None:
    """Pids whose command line mentions the fixture root; None when unmeasurable."""
    pgrep = shutil.which("pgrep")
    if os.name == "nt" or pgrep is None:
        return None
    try:
        out = subprocess.run(
            [pgrep, "-f", str(root)], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    if out.returncode not in (0, 1):
        return None
    return [p for p in out.stdout.split() if p.strip()]


def _pick_bundle(bundle_dir: Path | None, version: str, platform_key: str) -> Path | None:
    if bundle_dir is None or not version or not platform_key:
        return None
    wanted = (bundle_dir / f"lore-site-{version}-{platform_key}.zip").resolve()
    return wanted if wanted.is_file() else None


def _current_platform(python: Path, env: dict[str, str], work: Path) -> str:
    probe = _run(
        [
            str(python),
            "-c",
            "from lore.site_bundle import current_platform;print(current_platform() or '')",
        ],
        env=env,
        cwd=work,
    )
    return probe.stdout.decode().strip()


def _offline_probe(python: Path, env: dict[str, str], work: Path, library: Path) -> None:
    script = work / "offline_probe.py"
    script.write_text(_OFFLINE_PROBE, encoding="utf-8")
    probe_env = dict(env)
    probe_env["LORE_MAP_ENABLED"] = "0"
    probe = _run([str(python), str(script), str(library)], env=probe_env, cwd=work)
    try:
        out = json.loads(probe.stdout.decode())
    except (json.JSONDecodeError, ValueError):
        out = {}
    check(
        "offline guidance without network",
        bool(out.get("items")) and str(out.get("verdict")) == "ok" and out.get("summary"),
        (probe.stderr.decode("utf-8", "replace")[-200:] or str(out))[:250],
    )


def _write_evidence(artifacts: Path, mode: str) -> Path:
    EVIDENCE["ok"] = (
        EVIDENCE.get("completed") is True and bool(EVIDENCE.get("checks")) and not FAILURES
    )
    out = artifacts / f"smoke-{mode}.json"
    out.write_text(json.dumps(EVIDENCE, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    FAILURES.clear()
    EVIDENCE.clear()
    EVIDENCE["checks"] = []
    EVIDENCE["completed"] = False
    parser = argparse.ArgumentParser(prog="smoke_install.py")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--mode", choices=["core", "full"], required=True)
    parser.add_argument("--bundle-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    wheels = sorted(args.artifacts.glob("lore_solo-*.whl"))
    if len(wheels) != 1:
        print(
            f"expected exactly one wheel under {args.artifacts}, found {len(wheels)}",
            file=sys.stderr,
        )
        return 2
    wheel = wheels[0]
    full = args.mode == "full"
    EVIDENCE["mode"] = args.mode
    EVIDENCE["wheel"] = wheel.name
    try:
        _main(args, wheel, full)
        EVIDENCE["completed"] = True
    finally:
        out = _write_evidence(args.artifacts, args.mode)
        print(f"wrote {out}")
    return 1 if FAILURES else 0


def _main(args: argparse.Namespace, wheel: Path, full: bool) -> None:
    names = _wheel_contents(wheel)
    check("wheel has constraints", "lore/release_constraints.txt" in names)
    check("wheel has site manifest", "lore/site_bundles.json" in names)
    check("wheel has no frontend source", not any(n.startswith("web/") for n in names))
    check(
        "wheel has no env files",
        not any(
            Path(n).name == ".env" or Path(n).name.startswith(".env.") for n in names
        ),
    )
    version = _wheel_version(wheel)
    check("wheel version readable", bool(version), version)

    work = Path(tempfile.mkdtemp(prefix="lore-smoke-"))
    try:
        home, workspace, library = work / "home", work / "workspace", work / "library"
        home.mkdir()
        make_fixture(workspace, library)
        env = isolated_env(home, workspace, library)

        constraints = wheel_constraints(wheel, work)
        venv = make_venv(work / "venv", env)
        installed = install_wheel(venv, wheel, constraints, with_map=full, env=env)
        check(
            "wheel install",
            installed.returncode == 0,
            installed.stderr.decode("utf-8", "replace")[-300:],
        )
        if installed.returncode != 0:
            raise SystemExit(1)
        python = _venv_python(venv)
        probe = _run(
            [str(python), "-c", "import lore,sys;sys.stdout.write(str(lore.__file__))"],
            env=env,
            cwd=work,
        )
        location = probe.stdout.decode().strip()
        check(
            "import from isolated venv",
            location.startswith(str(venv)),
            location[:200],
        )
        resources = _run(
            [
                str(python),
                "-c",
                (
                    "from importlib.resources import files;"
                    "print((files('lore')/'release_constraints.txt').is_file(),"
                    "(files('lore')/'site_bundles.json').is_file())"
                ),
            ],
            env=env,
            cwd=work,
        )
        check("packaged resources readable", resources.stdout.decode().startswith("True True"))
        if not full:
            gone = _run(
                [
                    str(python),
                    "-c",
                    (
                        "import importlib.metadata as m;"
                        "print(any("
                        "d.metadata['Name']=='graphifyy' for d in m.distributions()))"
                    ),
                ],
                env=env,
                cwd=work,
            )
            check(
                "graphifyy distribution absent in core",
                gone.stdout.decode().strip() == "False",
                gone.stdout.decode().strip()[:100],
            )

        _mcp_checks(python, env)
        _offline_probe(python, env, work, library)

        if full:
            platform_key = _current_platform(python, env, work)
            check("platform detected", bool(platform_key), platform_key)
            bundle = _pick_bundle(args.bundle_dir, version, platform_key)
            check(
                "platform-matched site bundle",
                bundle is not None,
                f"lore-site-{version}-{platform_key}.zip",
            )
            repo = workspace / "fixture-repo"
            (repo / "src").mkdir(parents=True)
            (repo / "src" / "app.py").write_text(
                "import util\n\ndef main():\n    return util.helper()\n",
                encoding="utf-8",
            )
            (repo / "src" / "util.py").write_text(
                "def helper():\n    return 1\n", encoding="utf-8"
            )
            map_env = dict(env)
            map_env["LORE_WORKSPACE"] = str(repo)
            mapped = _run(
                [str(python), "-m", "lore", "map", str(repo)],
                env=map_env,
                cwd=repo,
            )
            graph_ok = False
            graph_path = repo / "graphify-out" / "graph.json"
            try:
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
                graph_ok = bool(graph.get("nodes"))
            except (OSError, json.JSONDecodeError):
                graph_ok = False
            check(
                "fixture map exits 0",
                mapped.returncode == 0,
                (mapped.stdout + mapped.stderr).decode("utf-8", "replace")[-200:],
            )
            check("fixture map graph nonempty", graph_ok)
            port = _free_port()
            if _port_busy(API_PORT):
                print(
                    f"setup API port {API_PORT} is already in use; aborting smoke",
                    file=sys.stderr,
                )
                raise SystemExit(2)
            if bundle is not None:
                _setup_smoke(python, env, bundle, port, args.artifacts)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

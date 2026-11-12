"""Start the setup site and print the address to open."""

from __future__ import annotations

import argparse
import importlib.util
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from lore import __version__
from lore.site_bundle import (
    SiteError,
    ensure_site,
    node_runtime,
    npm_command,
)

API_PORT = 7421
STARTUP_TIMEOUT = 30.0


@dataclass(frozen=True)
class _Site:
    server: Path | None = None
    dev_dir: Path | None = None
    note: str = ""


def format_banner(key: str, port: int = 3000) -> str:
    return f"http://127.0.0.1:{port}/?key={key}"


def serve_api() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lore.setup.settings")
    port = os.environ.get("LORE_SETUP_PORT", str(API_PORT))
    from django.core.management import execute_from_command_line

    execute_from_command_line(["django", "runserver", f"127.0.0.1:{port}", "--noreload"])


def _container() -> bool:
    return os.environ.get("LORE_CONTAINER", "").strip() == "1"


def _web_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "web"


def _load_builder() -> object | None:
    script = _web_dir().parent / "scripts" / "build_site_bundle.py"
    if not script.is_file():
        return None
    spec = importlib.util.spec_from_file_location("lore_build_site_bundle", script)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _standalone_current(web: Path, server: Path) -> bool:
    """A checkout standalone build is trusted only when its stamp still matches."""
    stamp = server.parent / ".lore-source-stamp"
    recipe = web.parent / "scripts" / "build_site_bundle.py"
    if not stamp.is_file() or not recipe.is_file():
        return False
    builder = _load_builder()
    if builder is None:
        return False
    try:
        current = builder.source_tree_hash(web, __version__, recipe)  # type: ignore[attr-defined]
    except OSError:
        return False
    return stamp.read_text(encoding="utf-8").strip() == current


def _resolve_site(site_bundle: Path | None, offline: bool) -> _Site:
    """Pick the standalone server or a source-dev directory."""
    env_dir = os.environ.get("LORE_WEB_DIR", "").strip()
    if env_dir:
        root = Path(env_dir)
        for candidate in (
            root / "server.js",
            root / ".next" / "standalone" / "server.js",
        ):
            if candidate.is_file():
                return _Site(server=candidate)
        if (root / "package.json").is_file():
            return _Site(dev_dir=root)
        raise SiteError(
            f"LORE_WEB_DIR={env_dir} has neither a standalone server.js nor a package.json."
        )
    if site_bundle is not None:
        resolved = ensure_site(site_bundle=site_bundle, offline=offline)
        return _Site(server=resolved.server, note=resolved.note)
    web = _web_dir()
    standalone = web / ".next" / "standalone" / "server.js"
    if standalone.is_file() and _standalone_current(web, standalone):
        return _Site(server=standalone)
    if (web / "package.json").is_file():
        return _Site(dev_dir=web)
    resolved = ensure_site(offline=offline)
    return _Site(server=resolved.server, note=resolved.note)


def _setup_log() -> IO[bytes]:
    path = Path.home() / ".lore" / "setup.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("wb")


def _spawn(
    command: list[str],
    *,
    cwd: Path | None,
    env: dict[str, str],
    log: IO[bytes],
) -> subprocess.Popen[bytes]:
    if os.name == "nt":
        return subprocess.Popen(
            command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT
        )
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _require_node() -> str:
    node = node_runtime()
    if node is None:
        raise SiteError(
            "The setup site needs Node 22 or newer. Install Node, then run "
            "lore-solo setup again. Lore itself does not need Node."
        )
    return node


def _start_web(
    env: dict[str, str], log: IO[bytes], site: _Site, port: int, node: str
) -> subprocess.Popen[bytes]:
    host = "0.0.0.0" if _container() else "127.0.0.1"
    if site.server is not None:
        web_env = dict(env)
        web_env["HOSTNAME"] = host
        web_env["PORT"] = str(port)
        return _spawn([node, "server.js"], cwd=site.server.parent, env=web_env, log=log)
    assert site.dev_dir is not None
    command = npm_command(
        "run", "dev", "--", "--hostname", host, "--port", str(port)
    )
    if command is None:
        raise SiteError(
            "Running the setup site from source needs npm "
            "(an npm CLI next to node on Windows)."
        )
    return _spawn(command, cwd=site.dev_dir, env=env, log=log)


def _probe(url: str, key: str) -> bool:
    request = urllib.request.Request(url)
    if key:
        request.add_header("X-Lore-Key", key)
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return bool(response.status == 200)
    except (urllib.error.URLError, OSError):
        return False


def _wait_ready(
    web_port: int,
    api_port: int,
    key: str,
    procs: list[subprocess.Popen[bytes]],
    timeout: float = STARTUP_TIMEOUT,
) -> None:
    browse_root = os.environ.get("LORE_WORKSPACE", "") if _container() else ""
    browse = urllib.parse.quote(browse_root or str(Path.home()))
    api_url = f"http://127.0.0.1:{api_port}/api/browse?path={browse}"
    proxy_url = f"http://127.0.0.1:{web_port}/api/browse?path={browse}"
    web_url = f"http://127.0.0.1:{web_port}/"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for proc in procs:
            code = proc.poll()
            if code is not None:
                raise SiteError(
                    f"A setup process exited ({code}) before the site was ready."
                )
        if (
            _probe(web_url, "")
            and _probe(api_url, key)
            and _probe(proxy_url, key)
        ):
            return
        time.sleep(0.3)
    raise SiteError(f"The setup site did not become ready within {timeout:.0f} seconds.")


def start_processes(
    key: str,
    *,
    site: _Site | None = None,
    port: int = 3000,
) -> list[subprocess.Popen[bytes]]:
    env = os.environ.copy()
    env["LORE_SETUP_KEY"] = key
    env["DJANGO_SETTINGS_MODULE"] = "lore.setup.settings"
    env["LORE_SETUP_PORT"] = str(API_PORT)
    env["LORE_API_PORT"] = str(API_PORT)
    site = site or _Site(dev_dir=_web_dir())
    node = _require_node()
    log = _setup_log()
    try:
        api = _spawn([sys.executable, "-m", "lore.setup_cmd", "--serve-api"], cwd=None, env=env, log=log)
        try:
            web = _start_web(env, log, site, port, node)
        except BaseException:
            _stop([api])
            raise
        return [api, web]
    finally:
        log.close()


def _stop(children: list[subprocess.Popen[bytes]]) -> None:
    for child in children:
        if child.poll() is None:
            if os.name == "nt":
                child.terminate()
            else:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except OSError:
                    child.terminate()
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                child.kill()
            else:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except OSError:
                    child.kill()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


def _web_port(args_port: int | None) -> int:
    if args_port is not None:
        port = args_port
        origin = "--port"
    else:
        raw = os.environ.get("LORE_WEB_PORT", "") or "3000"
        try:
            port = int(raw)
        except ValueError:
            raise SystemExit(f"LORE_WEB_PORT must be a port number, got {raw!r}") from None
        origin = "LORE_WEB_PORT"
    if not 1 <= port <= 65535:
        raise SystemExit(f"{origin} must be between 1 and 65535, got {port}")
    return port


def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lore-solo setup")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--site-bundle", type=Path, default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--serve-api", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(list(argv or []))
    if args.serve_api:
        serve_api()
        return
    port = _web_port(args.port)
    key = os.environ.get("LORE_SETUP_KEY") or secrets.token_urlsafe(24)
    os.environ["LORE_SETUP_KEY"] = key
    children: list[subprocess.Popen[bytes]] = []
    previous_break: Any = None
    break_signal = getattr(signal, "SIGBREAK", None)
    if os.name == "nt" and break_signal is not None:
        def _break(_signum: int, _frame: object) -> None:
            raise KeyboardInterrupt

        previous_break = signal.signal(break_signal, _break)
    try:
        site = _resolve_site(args.site_bundle, args.offline)
        children = start_processes(key, site=site, port=port)
        if children:
            _wait_ready(port, API_PORT, key, children)
        if site.note:
            print(site.note, file=sys.stderr)
        print(format_banner(key, port), flush=True)
        if not children:
            return
        log_path = Path.home() / ".lore" / "setup.log"
        while all(child.poll() is None for child in children):
            time.sleep(0.4)
        code = next(
            child.poll() for child in children if child.poll() is not None
        )
        raise SiteError(
            f"The setup site stopped unexpectedly ({code}). Details are in {log_path}"
        )
    except KeyboardInterrupt:
        pass
    except SiteError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        _stop(children)
        if previous_break is not None and break_signal is not None:
            signal.signal(break_signal, previous_break)


if __name__ == "__main__":
    run(sys.argv[1:])

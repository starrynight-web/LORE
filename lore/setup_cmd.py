"""Start the setup site and print the address to open."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import IO


def format_banner(key: str, port: int = 3000) -> str:
    return f"http://127.0.0.1:{port}/?key={key}"


def serve_api() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lore.setup.settings")
    port = os.environ.get("LORE_SETUP_PORT", "7421")
    from django.core.management import execute_from_command_line

    execute_from_command_line(["django", "runserver", f"127.0.0.1:{port}", "--noreload"])


def _web_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "web"


def _bundle_source() -> Path | None:
    bundled = Path(__file__).resolve().parent / "web_src"
    if (bundled / "package.json").is_file():
        return bundled
    return None


def _site_cache() -> Path:
    return Path.home() / ".lore" / "site"


def _source_stamp(source: Path) -> str:
    digest = hashlib.sha256()
    for name in ("package.json", "package-lock.json"):
        path = source / name
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _assemble_standalone(cache: Path) -> None:
    standalone = cache / ".next" / "standalone"
    static = cache / ".next" / "static"
    if static.is_dir():
        dest = standalone / ".next" / "static"
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(static, dest)
    public = cache / "public"
    if public.is_dir():
        dest_public = standalone / "public"
        if dest_public.exists():
            shutil.rmtree(dest_public)
        shutil.copytree(public, dest_public)


def _prepare_cached_site(source: Path) -> Path:
    cache = _site_cache()
    server = cache / ".next" / "standalone" / "server.js"
    stamp_path = cache / ".source-stamp"
    stamp = _source_stamp(source)
    if server.is_file() and stamp_path.is_file() and stamp_path.read_text(encoding="utf-8") == stamp:
        return server
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("The setup site needs Node.js. Install Node.js, then run lore-solo setup again.")
    if cache.exists():
        shutil.rmtree(cache)
    shutil.copytree(source, cache)
    print("Building the setup site...", flush=True)
    install = subprocess.run([npm, "ci"], cwd=cache, check=False)
    if install.returncode != 0:
        raise SystemExit("The setup site did not build.")
    build = subprocess.run([npm, "run", "build"], cwd=cache, check=False)
    if build.returncode != 0:
        raise SystemExit("The setup site did not build.")
    _assemble_standalone(cache)
    if not server.is_file():
        raise SystemExit("The setup site did not build.")
    stamp_path.write_text(stamp, encoding="utf-8")
    return server


def _ready_web() -> None:
    """Build the packaged site before the address is printed."""
    if os.environ.get("LORE_WEB_DIR", "").strip():
        return
    if (_web_dir() / ".next" / "standalone" / "server.js").is_file():
        return
    if (_web_dir() / "package.json").is_file():
        return
    source = _bundle_source()
    if source is None:
        return
    server = _prepare_cached_site(source)
    os.environ["LORE_WEB_DIR"] = str(server.parent)


def _standalone_server() -> Path | None:
    candidates: list[Path] = []
    web_dir = os.environ.get("LORE_WEB_DIR", "")
    if web_dir:
        candidates.append(Path(web_dir) / "server.js")
    candidates.append(_web_dir() / ".next" / "standalone" / "server.js")
    if not (_web_dir() / "package.json").is_file():
        candidates.append(_site_cache() / ".next" / "standalone" / "server.js")
    for server in candidates:
        if server.is_file():
            return server
    return None


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
    return subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)


def _start_web(env: dict[str, str], log: IO[bytes]) -> subprocess.Popen[bytes]:
    server = _standalone_server()
    if server is not None:
        node = shutil.which("node")
        if node is None:
            raise SystemExit("The setup site needs Node.js.")
        web_env = dict(env)
        web_env["HOSTNAME"] = "127.0.0.1"
        web_env["PORT"] = "3000"
        return _spawn([node, "server.js"], cwd=server.parent, env=web_env, log=log)
    source = _bundle_source()
    if source is not None:
        server = _prepare_cached_site(source)
        node = shutil.which("node")
        if node is None:
            raise SystemExit("The setup site needs Node.js.")
        web_env = dict(env)
        web_env["HOSTNAME"] = "127.0.0.1"
        web_env["PORT"] = "3000"
        return _spawn([node, "server.js"], cwd=server.parent, env=web_env, log=log)
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("The setup site needs Node.js.")
    return _spawn(
        [npm, "run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000"],
        cwd=_web_dir(),
        env=env,
        log=log,
    )


def start_processes(key: str) -> list[subprocess.Popen[bytes]]:
    env = os.environ.copy()
    env["LORE_SETUP_KEY"] = key
    env["DJANGO_SETTINGS_MODULE"] = "lore.setup.settings"
    env["LORE_SETUP_PORT"] = "7421"
    env["LORE_API_PORT"] = "7421"
    log = _setup_log()
    api = _spawn([sys.executable, "-m", "lore.setup_cmd", "--serve-api"], cwd=None, env=env, log=log)
    try:
        web = _start_web(env, log)
    except SystemExit:
        api.terminate()
        log.close()
        raise
    return [api, web]


def run(argv: list[str] | None = None) -> None:
    args = list(argv or [])
    if args[:1] == ["--serve-api"]:
        serve_api()
        return
    key = os.environ.get("LORE_SETUP_KEY") or secrets.token_urlsafe(24)
    os.environ["LORE_SETUP_KEY"] = key
    _ready_web()
    print(format_banner(key), flush=True)
    children = start_processes(key)
    log_path = Path.home() / ".lore" / "setup.log"
    try:
        while any(child.poll() is None for child in children):
            failed = [child for child in children if child.poll() not in (None, 0)]
            if failed:
                print(f"The setup site stopped. Details are in {log_path}", file=sys.stderr)
                break
            time.sleep(0.4)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    run(sys.argv[1:])

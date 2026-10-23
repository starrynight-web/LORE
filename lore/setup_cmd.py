"""Start the setup site and print the address to open."""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path


def format_banner(key: str, port: int = 3000) -> str:
    return "\n".join(
        [
            "Lore setup is running.",
            f"Open http://127.0.0.1:{port}/?key={key}",
        ]
    )


def serve_api() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lore.setup.settings")
    port = os.environ.get("LORE_SETUP_PORT", "7421")
    from django.core.management import execute_from_command_line

    execute_from_command_line(["django", "runserver", f"127.0.0.1:{port}", "--noreload"])


def _web_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "web"


def _standalone_server() -> Path | None:
    candidates: list[Path] = []
    web_dir = os.environ.get("LORE_WEB_DIR", "")
    if web_dir:
        candidates.append(Path(web_dir) / "server.js")
    candidates.append(_web_dir() / ".next" / "standalone" / "server.js")
    for server in candidates:
        if server.is_file():
            return server
    return None


def _start_web(env: dict[str, str]) -> subprocess.Popen[bytes]:
    server = _standalone_server()
    if server is not None:
        node = shutil.which("node")
        if node is None:
            raise SystemExit("The setup site is built, and Node.js is not installed.")
        web_env = dict(env)
        web_env["HOSTNAME"] = "127.0.0.1"
        web_env["PORT"] = "3000"
        return subprocess.Popen([node, "server.js"], cwd=server.parent, env=web_env)
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("The setup site is not built, and npm is not installed.")
    return subprocess.Popen(
        [npm, "run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000"],
        cwd=_web_dir(),
        env=env,
    )


def start_processes(key: str) -> list[subprocess.Popen[bytes]]:
    env = os.environ.copy()
    env["LORE_SETUP_KEY"] = key
    env["DJANGO_SETTINGS_MODULE"] = "lore.setup.settings"
    env["LORE_SETUP_PORT"] = "7421"
    env["LORE_API_PORT"] = "7421"
    api = subprocess.Popen(
        [sys.executable, "-m", "lore.setup_cmd", "--serve-api"],
        env=env,
    )
    try:
        web = _start_web(env)
    except SystemExit:
        api.terminate()
        raise
    return [api, web]


def run(argv: list[str] | None = None) -> None:
    args = list(argv or [])
    if args[:1] == ["--serve-api"]:
        serve_api()
        return
    key = os.environ.get("LORE_SETUP_KEY") or secrets.token_urlsafe(24)
    os.environ["LORE_SETUP_KEY"] = key
    print(format_banner(key), flush=True)
    children = start_processes(key)
    try:
        while any(child.poll() is None for child in children):
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

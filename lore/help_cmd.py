"""Top-level help catalog for lore-solo."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TextIO

COMMANDS: list[tuple[str, str]] = [
    ("install", "Install the lore-solo command on this computer"),
    ("update", "Upgrade lore-solo and refresh the cached setup site"),
    ("setup", "Start the local setup dashboard in your browser"),
    ("uninstall", "Remove the lore-solo command (keeps your library)"),
    ("connect", "Write editor/agent connection files for a project"),
    ("container", "Run Lore inside the demo container"),
    ("mcp", "Start the MCP server for coding agents"),
    ("map", "Build a codebase map for the current project"),
    ("doctor", "Check that Lore and optional tools are ready"),
    ("govern", "Scan skills and personas for governance findings"),
    ("help", "Show this help, or help for one command"),
]


def print_catalog(*, stream: TextIO | None = None) -> None:
    out: TextIO = stream if stream is not None else sys.stderr
    print("usage: lore-solo <command> [options]", file=out)
    print(file=out)
    print("Commands:", file=out)
    width = max(len(name) for name, _desc in COMMANDS)
    for name, desc in COMMANDS:
        print(f"  {name.ljust(width)}  {desc}", file=out)
    print(file=out)
    print("Run `lore-solo help <command>` or `lore-solo <command> -h` for details.", file=out)


def _command_help(name: str) -> int:
    runners: dict[str, Callable[[list[str]], object]] = {}

    def load() -> None:
        from lore import (
            doctor_cmd,
            govern_cmd,
            install_cmd,
            setup_cmd,
            uninstall_cmd,
            update_cmd,
        )
        from lore.container_cmd import run as run_container

        runners["install"] = install_cmd.run
        runners["update"] = update_cmd.run
        runners["setup"] = setup_cmd.run
        runners["uninstall"] = uninstall_cmd.run
        runners["doctor"] = doctor_cmd.run
        runners["govern"] = govern_cmd.run
        runners["container"] = run_container

    if name in {"connect", "mcp", "map"}:
        print(f"usage: lore-solo {name} [args]", file=sys.stderr)
        print(f"  See `lore-solo help` — {dict(COMMANDS).get(name, name)}.", file=sys.stderr)
        return 0
    if name == "help":
        print_catalog()
        return 0
    load()
    runner = runners.get(name)
    if runner is None:
        print_catalog()
        print(f"\nunknown command {name!r}", file=sys.stderr)
        return 2
    try:
        result = runner(["-h"])
    except SystemExit as exc:
        code = exc.code
        return 0 if code in (None, 0) else int(code) if isinstance(code, int) else 1
    return int(result) if isinstance(result, int) else 0


def run(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if not args or args[0] in {"-h", "--help"}:
        print_catalog()
        return 0
    return _command_help(args[0])

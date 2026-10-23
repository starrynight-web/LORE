"""`python -m lore mcp` and `python -m lore setup`."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("usage: python -m lore mcp|setup|connect", file=sys.stderr)
        return 0
    command, rest = args[0], args[1:]
    if command == "mcp":
        from lore.mcp import run as run_mcp

        run_mcp(rest)
        return 0
    if command == "setup":
        from lore.setup_cmd import run as run_setup

        run_setup(rest)
        return 0
    if command == "connect":
        from lore.connect import register_agents

        result = register_agents()
        for path in result["written"]:
            print(path)
        for skipped in result["skipped"]:
            print(f"skipped {skipped}", file=sys.stderr)
        return 0 if result["written"] else 1
    print(f"unknown command {command!r}; use mcp, setup, or connect", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

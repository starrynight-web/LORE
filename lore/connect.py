"""MCP entry for Lore, and the editor configs the connect command writes.

The command is a local process. The editor starts it with the open project as
its working directory.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
from pathlib import Path


def invocation() -> tuple[str, list[str]]:
    """The program an editor should start, and the arguments that select MCP."""
    explicit = os.environ.get("LORE_COMMAND", "").strip()
    if explicit:
        return explicit, ["mcp"]
    installed = _installed_command()
    if installed is not None:
        return str(installed), ["mcp"]
    for name in ("lore-solo", "lore"):
        found = shutil.which(name)
        if found:
            return found, ["mcp"]
    return "uvx", ["lore-solo", "mcp"]


def lore_command() -> str:
    """The program editors should start."""
    return invocation()[0]


def _installed_command() -> Path | None:
    bin_dir = Path.home() / ".lore" / "bin"
    for name in ("lore-solo", "lore"):
        base = bin_dir / name
        if os.name == "nt":
            windows = base.with_suffix(".exe")
            if windows.is_file():
                return windows
        if base.is_file():
            return base
    return None


def mcp_args() -> list[str]:
    return invocation()[1]


def mcp_entry(
    kind: str,
    command: str | None = None,
    client: str = "",
    args: list[str] | None = None,
) -> dict[str, object]:
    chosen, chosen_args = invocation()
    if command is not None:
        chosen = command
    if args is not None:
        chosen_args = args
    elif command is not None:
        chosen_args = ["mcp"]
    entry: dict[str, object] = {"command": chosen, "args": chosen_args}
    if kind == "vscode":
        entry["type"] = "stdio"
    name = client.strip()
    if name:
        entry["env"] = {"LORE_CLIENT": name}
    return entry


def install_command() -> str:
    launcher = os.environ.get("LORE_LAUNCHER", "").strip()
    if launcher:
        return f"{launcher} connect"
    return "uvx lore-solo connect"


def windows_command(command: str) -> str:
    if command.startswith("uvx "):
        return command
    suffix = " connect"
    if command.endswith(suffix):
        script = command[: -len(suffix)]
        if script.endswith(".ps1"):
            return command
        return f"{script}.ps1 connect"
    return "scripts/lore-solo.ps1 connect"


def agent_prompt(command: str | None = None) -> str:
    chosen = command or install_command()
    windows = windows_command(chosen)
    if windows == chosen:
        steps = f"On macOS, Linux, or Windows, run:\n\n{chosen}\n\n"
    else:
        steps = (
            "On macOS or Linux, run this in the shell:\n\n"
            f"{chosen}\n\n"
            "On Windows, run this in PowerShell:\n\n"
            f"{windows}\n\n"
        )
    return (
        "Register Lore with the editors on this computer. "
        f"{steps}"
        "When it finishes, confirm Lore is registered with the editors it found. "
        "A project that already has a .lore directory keeps using that directory."
    )


def host_system(value: str | None = None) -> str:
    raw = (value or os.environ.get("LORE_HOST_OS") or platform.system()).lower()
    if raw.startswith("darwin") or raw == "macos":
        return "darwin"
    if raw.startswith("win"):
        return "windows"
    return "linux"


def _write_json(path: Path, key: str, entry: dict[str, object]) -> None:
    data: dict[str, object] = {}
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            loaded = json.loads(raw)
            if not isinstance(loaded, dict):
                raise ValueError(f"{path} is not a JSON object.")
            data = loaded
        backup = path.with_name(path.name + ".lore.bak")
        if not backup.exists():
            shutil.copyfile(path, backup)
    servers = data.get(key)
    if not isinstance(servers, dict):
        servers = {}
    servers["lore"] = entry
    data[key] = servers
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _strip_toml_section(text: str, heading: str) -> str:
    kept: list[str] = []
    skipping = False
    blanks: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            skipping = stripped == heading or stripped.startswith(heading + " ")
        if skipping:
            continue
        if stripped == "":
            blanks.append(line)
            continue
        kept.extend(blanks)
        blanks = []
        kept.append(line)
    return "\n".join(kept).rstrip()


def _write_codex(path: Path, command: str, client: str = "", args: list[str] | None = None) -> None:
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if path.is_file():
        backup = path.with_name(path.name + ".lore.bak")
        if not backup.exists():
            shutil.copyfile(path, backup)
    kept = _strip_toml_section(existing, "[mcp_servers.lore]")
    rendered = ", ".join(json.dumps(part) for part in (args if args is not None else mcp_args()))
    env = ""
    if client.strip():
        env = f"env = {{ LORE_CLIENT = {json.dumps(client.strip())} }}\n"
    block = f"[mcp_servers.lore]\ncommand = {json.dumps(command)}\nargs = [{rendered}]\n{env}"
    body = f"{kept}\n\n{block}" if kept else block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")


def _targets(home: Path, system: str) -> list[tuple[str, Path, str, str]]:
    """(label, file, container key, editor). An editor is included when its folder exists."""
    if system == "darwin":
        desktop = home / "Library" / "Application Support" / "Claude"
        vscode = home / "Library" / "Application Support" / "Code" / "User"
    elif system == "windows":
        desktop = home / "AppData" / "Roaming" / "Claude"
        vscode = home / "AppData" / "Roaming" / "Code" / "User"
    else:
        desktop = home / ".config" / "Claude"
        vscode = home / ".config" / "Code" / "User"
    rows: list[tuple[str, Path, str, str]] = []
    cursor = home / ".cursor"
    if cursor.is_dir() or (cursor / "mcp.json").exists():
        rows.append(("Cursor", cursor / "mcp.json", "mcpServers", "cursor"))
    claude = home / ".claude.json"
    if claude.exists() or (home / ".claude").is_dir():
        rows.append(("Claude Code", claude, "mcpServers", "other"))
    if desktop.is_dir():
        rows.append(("Claude Desktop", desktop / "claude_desktop_config.json", "mcpServers", "other"))
    if (home / ".codex").is_dir():
        rows.append(("Codex", home / ".codex" / "config.toml", "", "codex"))
    if vscode.is_dir():
        rows.append(("VS Code", vscode / "mcp.json", "servers", "vscode"))
    gemini = home / ".gemini" / "config"
    if gemini.is_dir():
        rows.append(("Antigravity", gemini / "mcp_config.json", "mcpServers", "other"))
    return rows


def register_agents(
    home: Path | None = None,
    system: str | None = None,
) -> dict[str, list[str]]:
    """Write Lore into each detected editor. Other servers in those files stay."""
    if home is None:
        raw = os.environ.get("LORE_HOST_HOME", "")
        home = Path(raw) if raw else Path.home()
    host = host_system(system)
    command, args = invocation()
    written: list[str] = []
    skipped: list[str] = []
    for label, path, key, editor in _targets(home, host):
        try:
            if editor == "codex":
                _write_codex(path, command, client=label, args=args)
            else:
                _write_json(path, key, mcp_entry(editor, command, client=label, args=args))
        except (OSError, ValueError, json.JSONDecodeError):
            skipped.append(f"{label}: {path}")
            continue
        written.append(str(path))
    return {"written": written, "skipped": skipped}

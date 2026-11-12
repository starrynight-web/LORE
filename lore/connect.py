"""MCP entry for Lore, and the editor configs the connect command writes.

The command is a local process. The editor starts it with the open project as
its working directory. Server display name is always ``lore-solo`` (distinct
from Enterprise ``lore-enterprise-mcp``). The old Go ``lore`` binary is
deprecated; connect still strips leftover ``lore`` MCP keys if present.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
from pathlib import Path

from lore.core.instructions import RULE_BEGIN, RULE_END, STANDING_INSTRUCTIONS
from lore.core.paths import library_root

# JSON / TOML key and FastMCP advertised name (keep in sync with mcp_server.build).
MCP_SERVER_NAME = "lore-solo"
_LEGACY_SERVER_NAMES = ("lore",)


def invocation() -> tuple[str, list[str]]:
    """The program an editor should start, and the arguments that select MCP."""
    explicit = os.environ.get("LORE_COMMAND", "").strip()
    if explicit:
        return explicit, ["mcp"]
    installed = _installed_command()
    if installed is not None:
        return str(installed), ["mcp"]
    found = shutil.which("lore-solo")
    if found:
        return found, ["mcp"]
    from lore.release import published_spec

    return (
        "uvx",
        [
            "--managed-python",
            "--python",
            "3.12",
            "--no-build",
            published_spec(with_map=False),
            "mcp",
        ],
    )


def lore_command() -> str:
    """The program editors should start."""
    return invocation()[0]


def _installed_command() -> Path | None:
    bin_dir = Path.home() / ".lore" / "bin"
    base = bin_dir / "lore-solo"
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
    if command is not None:
        chosen = command
        chosen_args = args if args is not None else ["mcp"]
    else:
        chosen, default_args = invocation()
        chosen_args = args if args is not None else default_args
    entry: dict[str, object] = {"command": chosen, "args": chosen_args}
    if kind == "vscode":
        entry["type"] = "stdio"
    env: dict[str, str] = {}
    name = client.strip()
    if name:
        env["LORE_CLIENT"] = name
    workspace = os.environ.get("LORE_WORKSPACE", "").strip()
    if not workspace:
        workspace = str(Path.cwd())
    env["LORE_WORKSPACE"] = workspace
    entry["env"] = env
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


def _workspace() -> Path:
    raw = os.environ.get("LORE_WORKSPACE", "").strip()
    return Path(raw) if raw else Path.cwd()


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
    for legacy in _LEGACY_SERVER_NAMES:
        servers.pop(legacy, None)
    servers[MCP_SERVER_NAME] = entry
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
    kept = existing
    for heading in (
        '[mcp_servers.lore]',
        '[mcp_servers."lore-solo"]',
        "[mcp_servers.lore-solo]",
    ):
        kept = _strip_toml_section(kept, heading)
    rendered = ", ".join(json.dumps(part) for part in (args if args is not None else mcp_args()))
    env = ""
    if client.strip():
        env = f"env = {{ LORE_CLIENT = {json.dumps(client.strip())} }}\n"
    block = (
        f'[mcp_servers."{MCP_SERVER_NAME}"]\n'
        f"command = {json.dumps(command)}\n"
        f"args = [{rendered}]\n"
        f"{env}"
    )
    body = f"{kept}\n\n{block}" if kept else block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")


def _targets(home: Path, system: str) -> list[tuple[str, Path, str, str]]:
    """(label, file, container key, editor). An editor is included when its folder exists."""
    if system == "darwin":
        desktop = home / "Library" / "Application Support" / "Claude"
        vscode = home / "Library" / "Application Support" / "Code" / "User"
        devin_global = home / "Library" / "Application Support" / "devin"
    elif system == "windows":
        desktop = home / "AppData" / "Roaming" / "Claude"
        vscode = home / "AppData" / "Roaming" / "Code" / "User"
        devin_global = home / "AppData" / "Roaming" / "devin"
    else:
        desktop = home / ".config" / "Claude"
        vscode = home / ".config" / "Code" / "User"
        devin_global = home / ".config" / "devin"
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
    if devin_global.is_dir() or (devin_global / "mcp_config.json").exists():
        rows.append(("Devin", devin_global / "mcp_config.json", "mcpServers", "other"))
    return rows


def container_refusal() -> str:
    return (
        "Lore is running inside its container, so it cannot write editor "
        "configs here. On the host, run: lore-solo connect --runtime docker "
        "--image <image> --workspace <dir> --library <dir>"
    )


def _docker_invocation(
    command: str, args: list[str], image: str | None
) -> tuple[str, list[str]]:
    if not image or not image.strip():
        raise SystemExit("--image is required with --runtime docker")
    from lore.container_cmd import ContainerError, _validate_image, _validate_root

    try:
        checked_image = _validate_image(image.strip())
        host_workspace = _validate_root(_workspace(), "workspace")
        host_library = _validate_root(library_root(), "library")
    except ContainerError as exc:
        raise SystemExit(str(exc)) from exc
    if host_workspace == host_library:
        raise SystemExit("--workspace and --library must be different directories")
    base = list(args)
    if base and base[-1] == "mcp":
        base = base[:-1]
    return command, base + [
        "container",
        "mcp",
        "--image",
        checked_image,
        "--workspace",
        host_workspace,
        "--library",
        host_library,
    ]


def register_agents(
    home: Path | None = None,
    system: str | None = None,
    *,
    runtime: str = "native",
    image: str | None = None,
) -> dict[str, list[str]]:
    """Write Lore into each detected editor. Other servers in those files stay."""
    from lore.container_paths import active

    if active():
        raise SystemExit(container_refusal())
    if home is None:
        raw = os.environ.get("LORE_HOST_HOME", "")
        home = Path(raw) if raw else Path.home()
    host = host_system(system)
    command, args = invocation()
    if runtime == "docker":
        command, args = _docker_invocation(command, args, image)
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
    written.extend(_write_rules(home))
    written.extend(
        _write_project_files(_workspace(), home=home, command=command, args=args)
    )
    return {"written": written, "skipped": skipped}


def run_connect(argv: list[str] | None = None) -> dict[str, list[str]]:
    parser = argparse.ArgumentParser(prog="lore-solo connect")
    parser.add_argument("--runtime", choices=["native", "docker"], default="native")
    parser.add_argument("--image", default=None)
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--library", type=Path, default=None)
    args = parser.parse_args(list(argv or []))
    if args.workspace is not None:
        os.environ["LORE_WORKSPACE"] = str(args.workspace)
    if args.library is not None:
        os.environ["LORE_LIBRARY"] = str(args.library)
    return register_agents(runtime=args.runtime, image=args.image)


def cursor_rule() -> str:
    return (
        "---\n"
        "description: Ask Lore before searching a repository\n"
        "alwaysApply: true\n"
        "---\n\n"
        f"{STANDING_INSTRUCTIONS}\n"
    )


def antigravity_rule() -> str:
    return (
        "---\n"
        "trigger: always_on\n"
        "---\n\n"
        f"{STANDING_INSTRUCTIONS}\n"
    )


def _write_rules(home: Path) -> list[str]:
    """Standing instructions for editors whose config directory already exists."""
    written: list[str] = []
    cursor = home / ".cursor"
    if cursor.is_dir() or (cursor / "mcp.json").exists():
        path = cursor / "rules" / "lore.mdc"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cursor_rule(), encoding="utf-8")
        written.append(str(path))
    if (home / ".codex").is_dir():
        path = home / ".codex" / "AGENTS.md"
        _upsert_rule(path)
        written.append(str(path))
    if (home / ".claude").is_dir():
        path = home / ".claude" / "CLAUDE.md"
        _upsert_rule(path)
        written.append(str(path))
    return written


def _write_project_files(
    workspace: Path,
    *,
    home: Path,
    command: str,
    args: list[str],
) -> list[str]:
    """Repo-root rules and optional Devin / Antigravity / VS Code project files."""
    written: list[str] = []
    if not workspace.exists():
        return written
    agents = workspace / "AGENTS.md"
    _upsert_rule(agents)
    written.append(str(agents))

    agents_dir = workspace / ".agents" / "rules"
    gemini_cfg = home / ".gemini" / "config"
    if (workspace / ".agents").exists() or gemini_cfg.is_dir():
        agents_dir.mkdir(parents=True, exist_ok=True)
        path = agents_dir / "lore.md"
        path.write_text(antigravity_rule(), encoding="utf-8")
        written.append(str(path))

    vscode_user = (
        (home / ".config" / "Code" / "User").is_dir()
        or (home / "Library" / "Application Support" / "Code" / "User").is_dir()
        or (home / "AppData" / "Roaming" / "Code" / "User").is_dir()
    )
    if vscode_user or (workspace / ".vscode").exists():
        copilot = workspace / ".github" / "copilot-instructions.md"
        _upsert_rule(copilot)
        written.append(str(copilot))

    if (workspace / ".devin").exists() or (home / ".config" / "devin").is_dir():
        devin_dir = workspace / ".devin"
        devin_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            devin_dir / "mcp_config.json",
            "mcpServers",
            mcp_entry("other", command, client="Devin", args=args),
        )
        written.append(str(devin_dir / "mcp_config.json"))
    return written


def _upsert_rule(path: Path) -> None:
    block = f"{RULE_BEGIN}\n{STANDING_INSTRUCTIONS}\n{RULE_END}\n"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if RULE_BEGIN in existing and RULE_END in existing:
        pre, rest = existing.split(RULE_BEGIN, 1)
        _, post = rest.split(RULE_END, 1)
        text = pre.rstrip() + "\n\n" + block + post.lstrip("\n")
    elif existing.strip():
        text = existing.rstrip() + "\n\n" + block
    else:
        text = block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
